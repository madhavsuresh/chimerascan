'''
Created on Jan 30, 2011

@author: mkiyer

chimerascan: chimeric transcript discovery using RNA-seq

Copyright (C) 2011 Matthew Iyer

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''
import logging
import os

from chimerascan import pysam

from chimerascan.lib import config
from chimerascan.lib.base import LibraryTypes
from chimerascan.lib.sam import parse_pe_reads
from chimerascan.lib.chimera import Chimera, OrientationTags, ORIENTATION_TAG_NAME
from chimerascan.lib.batch_sort import batch_sort

from chimerascan.pipeline.find_discordant_reads import get_gene_orientation

def to_fastq(qname, readnum, seq, qual):
    return "@%s/%d\n%s\n+\n%s" % (qname, readnum+1, seq, qual)

def nominate_encomp_spanning_reads(chimera_file, output_fastq_file):
    """
    find all encompassing reads that should to be remapped to see if they
    span the breakpoint junction
    """
    fqfh = open(output_fastq_file, "w")
    remap_qnames = set()
    for c in Chimera.parse(open(chimera_file)):
        # find breakpoint coords of chimera
        end5p = c.tx_end_5p
        start3p = c.tx_start_3p
        for r5p,r3p in c.encomp_frags:            
            # if 5' read overlaps breakpoint then it should be remapped
            if r5p.clipstart < end5p < r5p.clipend:
                key5p = (r5p.qname, r5p.readnum)
                if key5p not in remap_qnames:
                    remap_qnames.add((r5p.qname, r5p.readnum))
                    print >>fqfh, to_fastq(r5p.qname, r5p.readnum, 
                                           r5p.seq, "I" * len(r5p.seq))
            # if 3' read overlaps breakpoint then it should be remapped
            if r3p.clipstart < start3p < r3p.clipend:
                key3p = (r3p.qname, r3p.readnum)
                if key3p not in remap_qnames:
                    remap_qnames.add((r3p.qname, r3p.readnum))
                    print >>fqfh, to_fastq(r3p.qname, r3p.readnum, 
                                           r3p.seq, "I" * len(r3p.seq))
    fqfh.close()
    return config.JOB_SUCCESS

def parse_chimeras_by_gene(chimera_file, orientation):
    clist = []
    prev_tx_name = None
    for c in Chimera.parse(open(chimera_file)):
        tx_name = c.tx_name_5p if (orientation == OrientationTags.FIVEPRIME) else c.tx_name_3p
        if prev_tx_name != tx_name:
            if len(clist) > 0:
                yield prev_tx_name, clist
                clist = []
            prev_tx_name = tx_name
        clist.append(c)
    if len(clist) > 0:
        yield prev_tx_name, clist

def parse_reads_by_rname(bamfh, orientation):
    """
    reads must be sorted and include an orientation tag
    """
    reads = []
    prev_rname = None
    for r in bamfh:
        o = r.opt(ORIENTATION_TAG_NAME)
        if o != orientation:
            continue
        if prev_rname != r.rname:
            if len(reads) > 0:
                yield reads
                reads = []
            prev_rname = r.rname
        reads.append(r)
    if len(reads) > 0:
        yield reads

def parse_sync_chimera_with_bam(chimera_file, bam_file, orientation):
    # setup iterators
    chimera_iter = parse_chimeras_by_gene(chimera_file, orientation)
    # get first item from each iterator
    try:
        tx_name, clist = chimera_iter.next()
        chimera_tx_name = config.GENE_REF_PREFIX + tx_name
    except StopIteration:
        return
    bamfh = pysam.Samfile(bam_file, "rb")
    try:
        for reads in parse_reads_by_rname(bamfh, orientation):
            read_tx_name = bamfh.references[reads[0].rname]        
            if read_tx_name < chimera_tx_name:
                continue
            while read_tx_name > chimera_tx_name:
                tx_name, clist = chimera_iter.next()
                chimera_tx_name = config.GENE_REF_PREFIX + tx_name
            if read_tx_name == chimera_tx_name:
                yield clist, reads, 
    except StopIteration:
        pass
    bamfh.close()

def nominate_unmapped_spanning_reads(chimera_file, unmapped_bam_file,
                                     onemap_fastq_file,
                                     unmapped_fastq_file,
                                     library_type,
                                     tmp_dir):
    # find all reads that need to be remapped to see if they span the 
    # breakpoint junction
    fqfh = open(unmapped_fastq_file, "w")
    # annotate mapped reads with sequence/quality of unmapped mate
    logging.debug("Annotating unmapped reads")
    bamfh = pysam.Samfile(unmapped_bam_file, "rb")    
    annot_single_mapped_bam_file = os.path.join(os.path.dirname(unmapped_bam_file), 
                                                "annotated_onemapper_reads.bam") 
    annot_bamfh = pysam.Samfile(annot_single_mapped_bam_file, "wb", template=bamfh)    
    # get list of 'gene' references in bam file to compare with
    gene_tids = set([tid for tid,refname in enumerate(bamfh.references)
                     if refname.startswith(config.GENE_REF_PREFIX)])
    for pe_reads in parse_pe_reads(bamfh):
        # find which of the original reads was unmapped        
        r1_unmapped = any(r.is_unmapped for r in pe_reads[0])
        r2_unmapped = any(r.is_unmapped for r in pe_reads[1])
        # if both reads unmapped, then remap to breakpoints
        if r1_unmapped and r2_unmapped:
            for readnum in (0,1):
                print >>fqfh, to_fastq(pe_reads[readnum][0].qname, readnum, 
                                       pe_reads[readnum][0].seq,
                                       pe_reads[readnum][0].qual)
        else:
            # annotate the mapped reads with the seq/qual of the
            # unmapped reads
            mapped_readnum = 0 if r2_unmapped else 1
            unmapped_readnum = 1 if r2_unmapped else 0            
            unmapped_seq = pe_reads[unmapped_readnum][0].seq
            unmapped_qual = pe_reads[unmapped_readnum][0].qual            
            for r in pe_reads[mapped_readnum]:
                # only consider gene mappings
                if r.rname not in gene_tids:
                    continue
                orientation = get_gene_orientation(r, library_type)
                # TODO: may need to REVERSE read here to get original
                r.tags = r.tags + [("R2", unmapped_seq), ("Q2", unmapped_qual),
                                   (ORIENTATION_TAG_NAME, orientation)]
                annot_bamfh.write(r)
    annot_bamfh.close()
    fqfh.close()
    # sort/index the annotated one-mapper unmapped reads by reference/position
    logging.debug("Sorting single-mapped mates by reference")
    sorted_annot_bam_file = os.path.splitext(annot_single_mapped_bam_file)[0] + ".srt.bam"
    sorted_annot_bam_prefix = os.path.splitext(sorted_annot_bam_file)[0]
    pysam.sort("-m", str(int(1e9)), annot_single_mapped_bam_file, sorted_annot_bam_prefix)
    pysam.index(sorted_annot_bam_file)
    fqfh = open(onemap_fastq_file, "w")
    # search for matches to 5' chimeras
    logging.debug("Matching single-mapped frags to 5' chimeras")
    for clist, reads in parse_sync_chimera_with_bam(chimera_file, 
                                                    sorted_annot_bam_file, 
                                                    OrientationTags.FIVEPRIME):
        # TODO: test more specifically that read has a chance to cross breakpoint
        for r in reads:
            # reverse read number
            readnum = 1 if r.is_read1 else 0
            print >>fqfh, to_fastq(r.qname, readnum, r.opt("R2"), r.opt("Q2"))
    # sort chimeras by 3' partner
    logging.debug("Sorting chimeras by 3' transcript")
    def sortfunc(line):
        fields = line.strip().split('\t', Chimera.TX_NAME_3P_FIELD+1)
        return fields[Chimera.TX_NAME_3P_FIELD]
    chimera_file_sorted_3p = os.path.join(tmp_dir, "tmp_chimeras.sorted3p.bedpe")
    batch_sort(input=chimera_file,
               output=chimera_file_sorted_3p,
               key=sortfunc,
               buffer_size=32000,
               tempdirs=[tmp_dir])
    # search for matches to 3' chimeras
    logging.debug("Matching single-mapped frags to 3' chimeras")
    for clist, reads in parse_sync_chimera_with_bam(chimera_file_sorted_3p, 
                                                    sorted_annot_bam_file, 
                                                    OrientationTags.THREEPRIME):
        # TODO: test more specifically that read has a chance to cross breakpoint
        for r in reads:
            # reverse read number for mate
            readnum = 1 if r.is_read1 else 0
            print >>fqfh, to_fastq(r.qname, readnum, r.opt("R2"), r.opt("Q2"))
    fqfh.close()
    os.remove(chimera_file_sorted_3p)
    return config.JOB_SUCCESS


def main():
    from optparse import OptionParser
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = OptionParser("usage: %prog [options] <chimeras.txt> "
                          "<unmapped_reads.bam> <encomp_remap.fq> "
                          "<onemap_remap.fq> "
                          "<unmapped_remap.fq> ")
    parser.add_option('--library', dest="library_type", 
                      default=LibraryTypes.FR_UNSTRANDED)
    options, args = parser.parse_args()
    chimera_file = args[0]
    bam_file = args[1]
    encomp_remap_fastq_file = args[2]
    onemap_remap_fastq_file = args[3]
    unmapped_remap_fastq_file = args[4]
    nominate_encomp_spanning_reads(chimera_file, encomp_remap_fastq_file)
    nominate_unmapped_spanning_reads(chimera_file, bam_file, 
                                     onemap_remap_fastq_file, 
                                     unmapped_remap_fastq_file,
                                     options.library_type,
                                     "/tmp")

if __name__ == '__main__':
    main()
