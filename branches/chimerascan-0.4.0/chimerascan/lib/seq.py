'''
Created on Jan 5, 2011

@author: Dan Blankenberg

Code from the Galaxy project (http://galaxy.psu.edu)
Contains methods to transform sequence strings
'''
import string
import re
import collections

#Translation table for reverse Complement, with ambiguity codes
DNA_COMPLEMENT = string.maketrans( "ACGTRYKMBDHVacgtrykmbdhv", "TGCAYRMKVHDBtgcayrmkvhdb" )
RNA_COMPLEMENT = string.maketrans( "ACGURYKMBDHVacgurykmbdhv", "UGCAYRMKVHDBugcayrmkvhdb" )
#Translation table for DNA <--> RNA
DNA_TO_RNA = string.maketrans( "Tt", "Uu" )
RNA_TO_DNA = string.maketrans( "Uu", "Tt" )

def DNA_complement( sequence ):
    '''complement DNA sequence string'''
    return sequence.translate( DNA_COMPLEMENT )
def DNA_reverse_complement( sequence ):
    '''returns the reverse complement of the sequence'''
    return DNA_complement(sequence[::-1])
def to_DNA( sequence ):
    return sequence.translate( DNA_TO_RNA )
#complement RNA sequence string
def RNA_complement( sequence ):
    return sequence.translate( RNA_COMPLEMENT )
def RNA_reverse_complement( self, sequence ):
    return RNA_complement( sequence[::-1] )
def to_RNA( sequence ):
    return sequence.translate( RNA_TO_DNA )

FASTQRecord = collections.namedtuple("FASTQRecord", ("qname", "seq", "qual", "readnum"))

def parse_fastq(line_iter):
    try:        
        qname = line_iter.next().rstrip()[1:]
        readnum = int(qname[-1])
        qname = qname[:-2]
        seq = line_iter.next().rstrip()
        line_iter.next()
        qual = line_iter.next().rstrip()
        yield FASTQRecord(qname, seq, qual, readnum)
        while True:
            # qname
            qname = line_iter.next().rstrip()[1:]
            readnum = int(qname[-1])
            qname = qname[:-2]
            # seq
            seq = line_iter.next().rstrip()
            # qname again (skip)
            line_iter.next()
            # qual
            qual = line_iter.next().rstrip()
            yield FASTQRecord(qname, seq, qual, readnum)
    except StopIteration:
        pass

def fastq_to_string(rec, suffix=""):
    return "@%s%s\n%s\n+\n%s" % (rec.qname, suffix, rec.seq, rec.qual)