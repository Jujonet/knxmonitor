#!/usr/bin/env python

import sys
import os
import getopt
import xml.etree.ElementTree as ET
import csv
import time
import codecs

devDict = {}
groupDict = {}

def to_unicode_or_bust(obj, encoding='utf-8'):
    if isinstance(obj,basestring):
        if not isinstance(obj,unicode):
            obj = unicode(obj, encoding)
    return obj

def utf_8_encoder(unicode_csv_data):
    for line in unicode_csv_data:
        yield line.encode('utf-8')

def unicode_csv_reader(unicode_csv_data, dialect=csv.excel, **kwargs):
    # csv.py doesn't do Unicode; encode temporarily as UTF-8:
    csv_reader = csv.reader(utf_8_encoder(unicode_csv_data),
                            dialect=dialect, **kwargs)
    for row in csv_reader:
        # decode UTF-8 back to Unicode, cell by cell:
        yield [unicode(cell, 'utf-8') for cell in row]
        
class KnxParseException(Exception):
    pass

def getFrom(text):
    try:
        s = text[text.find(" from ")+6:]
        s = s[:s.find(" ")]
        fromaddr = s

        # Sanity check
        
        a,b,c = s.split(".")
        
        if int(a) < 0 or int(a) > 0x1F:
            raise KnxParseException
        if int(b) < 0 or int(b) > 0x7:
            raise KnxParseException
        if int(c) < 0 or int(c) > 0xFF:
            raise KnxParseException
        
    except:
        # Something failed, but we only want to cause
        # one type of exception...
        raise KnxParseException
    
    if s in devDict.keys():
        s = devDict[s]
        
    s = "%s(%s)" %(s, fromaddr)
    return s

def getTo(text):
    
    try:
        s = text[text.find(" to ")+4:]
        s = s[:s.find(" ")]
        toaddr = s
        
        # Sanity check
        
        a,b,c = s.split("/")
        
        if int(a) < 0 or int(a) > 0x1F:
            raise KnxParseException
        if int(b) < 0 or int(b) > 0x7:
            raise KnxParseException
        if int(c) < 0 or int(c) > 0xFF:
            raise KnxParseException
        
    except:
        # Something failed, but we only want to cause
        # one type of exception...
        raise KnxParseException
    
    if s in groupDict.keys():
        s = groupDict[s]

    s = "%s(%s)" %(s, toaddr)
    return s


def getValue(text):
    #print text
    try:
        l = text.strip().split()
        l2 = []
        s =""
        # Throw away last chunk, its the \x00 terminator...
        #l.pop()
        while True:
            x = l.pop()
            try:
                y = int(x,16)
            except ValueError:
                # Ok, hit a non-hex value, that must
                # mean that we are finished...
                break
            l2.append(x)
        l2.reverse()
        for x in l2:
            s += "%s " %x
    except:
        # Something failed, but we only want to cause
        # one type of exception...
        raise KnxParseException
    s = s.strip()
    #print s
    return s


def parseVbusOutput(text, origtime):
    sender = unicode(getFrom(text))
    receiver = unicode(getTo(text).decode("utf-8"))
    value = unicode(getValue(text))
    try:
        s = "%s: Device %s   -> GroupAddress %s: %s" %(origtime,
                                                       sender, receiver, value)
    except:
        # Failed in conversion...
        s = text
    #raise KnxParseException
    return s
    


def loadGroupAddrs(filename):
    
    #reader = csv.reader(codecs.EncodedFile(open(filename, "rb"),
    #                                       'utf-8',
    #                                       'iso-8859-15'),
    #                    delimiter=";")
    reader = csv.reader(open(filename, "rb"), delimiter=";")
    
    for main,middle,sub,address in reader:
        if main.strip() != '':
            main2 = main.strip()
        if middle.strip() != '':
            middle2 = middle.strip()
        if sub.strip() != '':
            sub2 = sub.strip()
        groupDict[address] = "%s - %s - %s" %(main2,middle2,sub2)

def loadDeviceAddrs(filename):

    #f = codecs.EncodedFile(open(filename, 'rb'), 'utf-16-le', 'utf-16')
    root = ET.parse(filename).getroot()
    rows = root.find("rows").findall("row")
    for row in rows:
        cols = row.findall("colValue")
        for c in cols:
            if c.attrib["nr"] == "1":
                #addr = to_unicode_or_bust(c.text)
                addr = c.text
            if c.attrib["nr"] == "2":
                #room = to_unicode_or_bust(c.text)
                room = c.text
            if c.attrib["nr"] == "4":
                #desc = to_unicode_or_bust(c.text)
                desc = c.text
        if room != None and len(room) > 0:
            desc = "%s - %s" %(room,desc)
        if len(addr) > 0  and len(desc) > 0:
            devDict[addr] = desc

if __name__ == "__main__":

    if len(sys.argv) != 2:
        print "usage: %s <filename>" % sys.argv[0];
        sys.exit(1);

    loadGroupAddrs("groupaddresses.csv")
    loadDeviceAddrs("enheter.xml")

    try:
        fn = sys.argv[1]
        inf = open(fn, "r")
        lines = inf.readlines()
    except:
        print "unable to open or read file: %s" %fn
        sys.exit(1)

    for line in lines:
        if line.find("LPDU") != -1:

            front = line[:line.find("(")]
            mid = line[line.find("(LP")+1:line.find("):")-1]
            end = line[line.find(")")+1:]

            origtime = front[:front.find("2010:")+4]
            
            try:
                s = parseVbusOutput(mid + " ", origtime)
                #print s
                #sys.exit(1)
            except KnxParseException:
                # Failed to parse, just print the original instead...
                
                s  = "Parse error: %s" %mid
                print s
            
            #print mid
            print s.encode("utf-8")
            #print front + end
        else:
            #continue
            print line.strip()
