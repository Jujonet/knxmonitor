import sys
import codecs
import xml.etree.ElementTree as ET
import csv
import time
import math
from optparse import OptionParser, OptionValueError
import Gnuplot

verbose = False

globDbgMsg = ""

def printVerbose(str):
    if verbose:
        print str


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")

class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self


class KnxParseException(Exception):
    pass


class KnxPdu(object):

    def __init__(self, devdict, groupdict, pdu_text):

        self.devDict = devdict
        self.groupDict = groupdict

        # Do parsing up front...
        self.text = pdu_text[pdu_text.find(" from ")+6:]

        try:
            s, rest = self.text.split(" ", 1) #[:self.text.find(" ")]
            
            # Sanity check
            
            a,b,c = s.split(".")
            
            if int(a) < 0 or int(a) > 0x1F:
                raise KnxParseException
            if int(b) < 0 or int(b) > 0x1F:
                raise KnxParseException
            if int(c) < 0 or int(c) > 0xFF:
                raise KnxParseException
        except:
            # Something failed, but we only want to cause
            # one type of exception...
            raise KnxParseException
    
        try:
            s = "%s(%s)" %(self.devDict[s]["Beskrivelse"], s)
        except KeyError:
            s = "(%s)" %(s)

        self.fromadr = unicode(s)

        # Receiving group address
        tmp, toaddr, rest = rest.split(" ", 2) #s[:s.find(" ")]
        self.toaddr = unicode(toaddr)
        
        #print rest
        # Value

        if ("GroupValue_Read" in rest):
            self.value = u"(read)"
        else:
            tmp, s = rest[rest.find("GroupValue_") + 14:].split(" ", 1)
            self.value = s.strip()
            i = self.value.find("(small)")
            if i != -1:
                self.value = self.value[i+8:]
            while not self.value[-1].isalnum():
                self.value = self.value[:-1]

        #print "(%s)"%self.value
        
    def getFrom(self):
            
        return self.fromadr

    def getTo(self):
        
        return self.toaddr #unicode(self.toaddr)
    
    def getValue(self):
            
        return self.value #unicode(s)


class KnxAddressStream(object):

    def __init__(self, address, addressInfo, type, flanksOnly):

        self.address    = address
        self.addrInfo   = addressInfo
        self.type       = type
        self.flanksOnly = flanksOnly
        self.maxVal    = None
        self.minVal    = None

        self.telegrams = []

    def errorExit(self, str):

        print "%s: %s" %(self.address, str)
        sys.exit(1)

    #
    # Temp
    #
    #hex    07        F9
    #bin  0000 0111  1111 1001
    #
    #hex    0C        8F
    #bin  0000 1100  1000 1111
    #
    # (0,01*M*)2^E 
    #
    # M = 100 1000 1111
    # E = 1
    #dec 23,34
    #
    def val2tempOld(self, val):
        
        if len(val) != 5:
            self.errorExit("error, value is not 16bit: %s" %val)

        z,x = val.split(" ")
        
        e = (int(z,16) & 0x78) >> 3
        m = (int(z,16) & 0x7)<<8 | int(x,16)
        
        val2 = (0.01*float(m))*math.pow(2, e)
        
        #if val2 < 10:
        #    print val
        #    print e
        #    print z
        return val2.__format__(".2f")
    

    def val2temp(self, val):
        z,x = val.split(" ")
        i = (int(z,16)*256) + int(x,16)
        s = (i & 0x8000) >> 15
        e = (i & 0x7800) >> 11
        m = i & 0x7FF
        if s == 1:
            m2 = (~(m-1)) & 0x7ff
            #print m2
            m2 = -m2
            #print m2
        else:
            m2 = m
        val2 = float((1<<e)*0.01*m2)
        if s == 10:
            print "e %x" %e
            print "%X" %m
            print "%X (%d, %d)" %(m2,m2,val2)
            print "%f" %val2
            sys.exit(1)
        #print "e = %x" %e
        return val2.__format__(".2f")


    # Varme styring %
    #
    #hex     9C
    #bin   1001 1100
    #dec  156 / 2.55 = 61.17%
    #
    def val2percent(self, val, scaling):
        
        if len(val) != 2:
            self.errorExit("error, value is not 8bit: %s" %val)

        s = int(scaling[1:]) if scaling != "%" else 1

        f = (float(int(val, 16)) / 2.55)/s
        
        return f.__format__(".2f")

 
    #  
    # Tid:
    #
    # hex    75         32      00
    # bin  0111 0101 0011 0101 0000 0000
    # dec    21        53       00
    def val2time(self, val):

        if len(val) != 8:
            self.errorExit("error, value is not 24bit: %s" %val)
            
        dh,m,s = val.split(" ")

        s = int(s,16) & 0x3f
        m = int(m,16) & 0x3f
        h = int(dh,16) & 0x1f
        d = (int(dh,16) & 0xe0) >> 5
        
        days = ["no day","mon","tue","wed","thu","fri","sat","sun"]
        
        return "%s %s:%s:%s" %(days[d],h,m,s)

    def val2onoff(self, val):

        if len(val) != 2:
            self.errorExit("error, value is not 8bit: %s" %val)

        # if val != "00" and val != "01":
        #    self.errorExit("error, onoff type only handles 00 or 01, not: %s" %val)

        if val == "00":
            return "0"
        else:
            return "1"

            
    def addTelegram(self, seq, timestamp, sender, value):

        # Don't try to decode (read) telegrams...
        if value != "(read)":
            # Decode according to any specified type..
            if self.type != None and self.type[0] == "%":
                s = self.val2percent(value, self.type)
            elif self.type == "temp":
                # print s
                s = self.val2temp(value)
                if self.minVal == None or float(self.minVal) > float(s):
                    self.minVal = s
                if self.maxVal == None or float(self.maxVal) < float(s):
                    self.maxVal = s
            elif self.type == "time":
                # print s
                s = self.val2time(value)
            elif self.type == "onoff":
                # print s
                s = self.val2onoff(value)                
            else:
                s = value
        else:
            s = value

        self.telegrams.append((seq, timestamp, sender, s))

    def prepareSynchronizedPrints(self):

        self.nextidx = 0
        self.lastValue = {}
        
    def printTelegrams(self, printseq):

        # Check if we have more telegrams to print...
        if self.nextidx >= len(self.telegrams):
           return False
           
        seq, ts, sender, value = self.telegrams[self.nextidx]

        #
        # Check if its our turn to print...
        #
        if seq != printseq:
            # Nope
            return True

        receiver = self.addrInfo["sub"]

        #print "entering: %8s -> %s   %s" %(self.address, printseq, self.telegrams[self.nextidx])
        
        #
        # Ok, if we get this far we are supposed to print something
        #

        # If only printing changes, we must check if a value has changed
        if sender not in self.lastValue.keys():
            self.lastValue[sender] = None
            
        if not self.flanksOnly or (self.flanksOnly and value != self.lastValue[sender]):
            self.lastValue[sender] = value

            if len(sender)>50:
                self.errorExit("to long sender: %s(%d)" %(sender, len(sender)))
            if len(receiver)>60:
                self.errorExit("to long receiver: %s(%d)" %(receiver, len(receiver)))

            try:
                outstr = "%s: %50s -> %60s(%s): %s" %(ts, sender, receiver,
                                                      self.address, value)
                print outstr
            except UnicodeEncodeError,err:
                #print "%s"%ts.decode("utf-8")
                #print "%s"%sender
                #print "%s"%receiver.decode("utf-8")
                #print "%s"%self.address.decode("utf-8")
                #print "%s"%value.decode("utf-8")
                #print "(%s) %s: %50s -> %60s(%s): %s" %(seq,ts, sender, receiver.decode("utf-8"),
                #                                        self.address, value)
                raise err
            except UnicodeDecodeError,err:
                #print "%s"%ts.decode("utf-8")
                #print "%s"%sender
                #print "%s"%receiver.decode("utf-8")
                #print "%s"%self.address.decode("utf-8")
                #print "%s"%value.decode("utf-8")
                #print "(%s) %s: %50s -> %60s(%s): %s" %(seq,ts, sender, receiver.decode("utf-8"),
                #                                        self.address, value)
                raise err
                    
        # Do we have more to print?
        self.nextidx += 1
        if self.nextidx >= len(self.telegrams):
            return False
        # Not done yet
        return True

    def preparePlotData(self, basetime):

        plotData = { "data"   : [],
                     "params" : "",
                     "title"  : self.addrInfo["sub"],
                     "style"  : "linespoints" }

        for t in self.telegrams:
            
            seq, ts, sender, value = t

            skip = False
            
            try:
                timedata = time.mktime(time.strptime(ts))
            except ValueError:
                printVerbose("timestamp error: %s" %ts)
                skip = True
            
            if self.type == "time":
                try:
                    val = time.mktime(time.strptime("2010 "+value, "%Y %a %H:%M:%S")) - basetime
                except ValueError:
                    printVerbose("value error: %s" %value)
                    skip = True
            else:
                try:
                    # Assume hex value
                    val = float(int(value, 16))
                except ValueError:
                    # Then try float directly
                    try:
                        val = float(value)
                    except ValueError:
                        printVerbose("value error: %s" %value)
                        skip = True

            if not skip:
                plotData["data"].append([timedata, val ])


        # Only smooth data of type 'temp' or '%'
        if (self.type in ["temp", "%"]) or (self.type != None and self.type[0] == "%"):
            plotData["smoothing"] = " smooth unique"
        else:
            plotData["smoothing"] = ""

        plotData["params"] = '1:2 '

        return plotData

class KnxParser(object):

    devDict   = {}
    groupDict = {}

    knxAddrStream = {}

    def __init__(self, devicesfilename,
                 groupaddrfilename, dumpaddressinfo = False,
                 flanksOnly = False, types = None):

        # Load device and address info
        self.loadGroupAddrs(groupaddrfilename, dumpaddressinfo, types, flanksOnly)
        self.loadDeviceAddrs(devicesfilename)

    def loadGroupAddrs(self, filename, dump, types, flanksOnly):
    
        #reader = csv.reader(open(filename, "rb"), delimiter=";")
        reader = UnicodeReader(open(filename, "rb"), delimiter=";")
        for main,middle,sub,address in reader:
            gdict = { "main" : main,
                      "middle" : middle,
                      "sub" : sub,
                      "address" : address }

            # Sanity check, skip non-valid addresses
            # print address
            try:
                a,b,c = address.split("/")
            
                if int(a) < 0 or int(a) > 0x1F:
                    continue
                if int(b) < 0 or int(b) > 0x7:
                    continue
                if int(c) < 0 or int(c) > 0xFF:
                    continue
            except ValueError:
                continue
                
            
            self.groupDict[address] = gdict

        if dump:
            self.dumpGaTable()
            sys.exit(0)

        # Populate streams dictionary
        for k in self.groupDict.keys():
            if k in types.keys():
                t = types[k]
            else:
                t = None
            self.knxAddrStream[k] = KnxAddressStream(k, self.groupDict[k],
                                                     t, flanksOnly)
            
            
    def loadDeviceAddrs(self, filename):
        
        root = ET.parse(filename).getroot()
        
        # First find the layout
        layout = {}
        cnames = root.find("columns").findall("colName")
        for cn in cnames:
            # print cn.attrib["nr"] + ": " + cn.text
            # layout[cn.text] = cn.attrib["nr"]
            layout[cn.attrib["nr"]] = cn.text
    
        # Then read in the device info, and build device dictionary
        rows = root.find("rows").findall("row")
        for row in rows:
            ddict = {}
            cols = row.findall("colValue")
            for c in cols:
                ddict[layout[c.attrib["nr"]]] = c.text
            self.devDict[ddict["Adresse"]] = ddict

    def dumpGaTable(self):
        
        print "Group addresses:"
        keys = self.groupDict.keys()
        keys.sort()
        for k in keys:
            print "%8s - %s %s %s" %(self.groupDict[k]["address"],
                                     self.groupDict[k]["main"],
                                     self.groupDict[k]["middle"],
                                     self.groupDict[k]["sub"])
        
    def setTimeBase(self, basetime):

        self.basetime = basetime

    def parseVbusOutput(self, seq, timestamp, text):

        # Skip programming related PDUs...
        if text.find("Data system") != -1:
            return
        
        pdu = KnxPdu(self.devDict, self.groupDict, text)
        
        sender = pdu.getFrom()
        receiver_raw = pdu.getTo()

        value = pdu.getValue()
        
        try:
            self.knxAddrStream[receiver_raw].addTelegram(seq, timestamp, sender, value)
        except KeyError:
            printVerbose("unknown address, skipping: %s" %receiver_raw)


    def getStreamMinMaxValues(self, groupAddr):
        
        try:
            min = self.knxAddrStream[groupAddr].minVal
            max = self.knxAddrStream[groupAddr].maxVal
            return min,max
        except:
            return None,None

    def printStreams(self, groupAddrs):

        if groupAddrs == None:
            # Logically, "none" means all :)
            groupAddrs = self.knxAddrStream.keys()
            
        for g in groupAddrs:
            self.knxAddrStream[g].prepareSynchronizedPrints()

        seq = 0
        more = True
        while more:
            more = False
            for g in groupAddrs:
                hasMore = self.knxAddrStream[g].printTelegrams(seq)
                more = more or hasMore


            # Step sequence number
            seq += 1

    def plotStreams(self, groupAddrs, genImage="", addHorLine=None):

        if groupAddrs == None:
            # Logically, "none" means all :)
            groupAddrs = self.knxAddrStream.keys()

        plotter = {}
        gdata = []
        plotData = None
        endTime = 0.0
        startTime = time.time() + (3600*24*365*10)
        for ga in groupAddrs:

            try:
                plotData = self.knxAddrStream[ga].preparePlotData(self.basetime)
            except KeyError:
                # Not a valid group address, skip it...
                continue
            
            if len(plotData["data"]) > 0:

                st, tmp = plotData["data"][0]
                et, tmp = plotData["data"][-1]
                if st < startTime:
                    startTime = st
                if et > endTime:
                    endTime = et
                kwarg = { "using" : plotData["params"],
                          "title" : plotData["title"].encode("utf-8"),
                          "with" : plotData["style"] + plotData["smoothing"] }
                gdata.append(Gnuplot.Data( plotData["data"], **kwarg ))

        # Add a horisontal line, if requested
        if plotData != None and addHorLine != None:
            try:
                dummy = iter(addHorLine)
            except TypeError:
                addHorLine = [addHorLine]
            for hl in addHorLine:

                kwarg = { "using" : "1:2",
                          "title" : "horisontal line at %s" %hl,
                          "with" : "linespoints smooth unique" }
                gdata.append(Gnuplot.Data( [ [startTime, hl],
                                             [endTime, hl] ], **kwarg ))
                        
                
        plotter = Gnuplot.Gnuplot(debug=1)
        plotter('set xdata time')
        plotter('set timefmt "%s"')
        plotter('set format x "%d/%m"')
        plotter('set grid')
        #plotter('set style fill solid')
        plotter('set key bottom left')

        if len(gdata) < 1:
            print "No data.."
            return
        
        plotter.plot(gdata[0])
        for g in gdata[1:]:
            plotter.replot(g)

        if genImage != "":
            plotter('set terminal png color')
            plotter('set output "%s"' %genImage)
            plotter.replot()
        else:
            raw_input('Please press return to exit...\n')
            
    


class KnxLogViewer(object):

    def __init__(self, devicesfilename, groupaddrfilename, infilenames,
                 dumpGAtable, types, flanksOnly, tail, groupAddressSet = None):

        self.delta = 0
        self.delta2 = 0
        self.pduCount = 0
        self.pduSkipped = 0
        self.dbgMsg = "groupAddressSet = %s" %str(groupAddressSet)
        start = time.time()

        #
        # Read in all the files...
        #
        lines = []
        for infilename in infilenames:
            try:
                inf = open(infilename, "r")
            except IOError:
                print "%s: Unable to open file: %s" %(sys.argv[0], infilename)
                sys.exit(1);
            except:
                op.print_help()
                sys.exit(1);
                
            print "Reading file: %s" % infilename
            lines.extend(inf.readlines())

            inf.close()

        print "Creating parser..."
        self.knx = KnxParser(devicesfilename, groupaddrfilename,
                             dumpGAtable, flanksOnly, types)
    
        
        if tail != 0:
            if tail < len(lines):
                lines = lines[len(lines) - tail :]
            
        #
        # Parsing the input...
        #
        basetime = 0
        lineNo = 0
        for line in lines:
            # Skip empty lines...
            if len(line.strip()) < 1:
                continue

            # If filter specified, skip unwanted GAs
            if groupAddressSet != None:
                ignore = True
                for ga in groupAddressSet:
                    if line.find(ga) != -1:
                        ignore = False
                        break
                if ignore:
                    self.pduSkipped += 1
                    continue
                
            lineNo += 1
        
            # Split timestamp from rest...
            try:
                timestamp, pdu = line.split(":LPDU:")
            except ValueError:
                timestamp, pdu = line.split("LPDU:")

            try:
                if basetime == 0:
                    basetime = time.mktime(time.strptime(timestamp, "%a %b %d %H:%M:%S %Y"))
                    # print timestamp
                    self.knx.setTimeBase(basetime)
            except ValueError:
                printVerbose("timestamp error: %s" %timestamp)

            try:
                self.knx.parseVbusOutput(lineNo, timestamp, pdu)
                self.pduCount += 1
            except KnxParseException:
                print "Failed: %s:  %s" %(lineNo, pdu)
                sys.exit(1)
            
            if lineNo % 10000 == 0:
                print "Parsed %d lines..." %lineNo
        print "Parsed %d lines..." %lineNo
        self.dbgMsg += "Parsed %d lines..." %lineNo
        
        self.delta = time.time() - start
    
    def getPerfData(self):

        s = "<p>"
        if self.delta != 0:
            s += "KnxLogViewer: Time used for init:    %f (%d PDUs parsed, %d skipped)<p>" %(self.delta, self.pduCount, self.pduSkipped)
            s += "Debug: %s<p>GlobalDebug:%s<p>" %(self.dbgMsg, globDbgMsg)
            self.delta = 0
        s += "KnxLogViewer: Time used for plotgen: %f<p>" %self.delta2
        s += "<p>"
        return s

    def getMinMaxValues(self, groupAddr):
        return self.knx.getStreamMinMaxValues(groupAddr)

    def plotLog(self, groupAddrs, plotImage, addHorLine=None):
        start = time.time()
        self.knx.plotStreams(groupAddrs, plotImage, addHorLine)
        self.delta2 = time.time() - start
        
    def printLog(self, groupAddrs):

        self.knx.printStreams(groupAddrs)


    
if __name__ == "__main__":

    groupAddrs = []
    types      = {}
    
    def groupAddr_callback(option, opt_str, value, parser):
        assert value is None
        value = []

        def floatable(str):
            try:
                float(str)
                return True
            except ValueError:
                return False

        for arg in parser.rargs:
            # stop on --foo like options
            if arg[:2] == "--" and len(arg) > 2:
                break
            # stop on -a, but not on -3 or -3.0
            if arg[:1] == "-" and len(arg) > 1 and not floatable(arg):
                break
            value.append(arg)

        del parser.rargs[:len(value)]

        if len(value) == 0:
            raise OptionValueError("-g option requires one or two arguments")
        
        groupAddrs.append(value[0])
        
        if len(value) > 1:
            t = value[1]
            if t not in ["onoff", "temp", "time", "%"]:
                # We also allow %<scaling factor>
                if t[0] != "%" or not str.isdigit(t[1:]):
                    raise OptionValueError("type argument for group addresses must "
                                           "be either 'onoff', 'temp', 'time', or '%%[<x>]', not: %s" %t)
            types[value[0]] = t

        

    op = OptionParser()

    op.add_option("-d", "--dump-group-addresses", dest="dumpGAtable", action="store_true",
                  help="dump group address table and exit")

    op.add_option("-i", "--input", dest="infilenames", action="append",
                  help="read log from  FILE", metavar="<FILE>")

    #op.add_option("-g", "--group-address", dest="groupAddrs", type="string", action="append",
    #              help="print only this group address(es) (can be repeated)", metavar="<GROUP ADDR>")

    op.add_option("-g", "--group-address", action="callback", callback=groupAddr_callback,
                  help="Specify which group address(es) to print, and optionally "
                  "what type to convert the value to")

    #op.add_option("-t", "--type", dest="types", action="append", choices=["%", "time", "temp"],
    #              help="convert value to specified type", metavar="<TYPE>")

    op.add_option("-f", "--flanks-only", dest="flanksOnly", action="store_true",
                  help="only print telegrams when values has changed since last telegram")

    op.add_option("-p", "--plot", dest="plot", action="store_true",
                  help="plot chart of data")

    op.add_option("-v", "--verbose", dest="verbose", action="store_true",
                  help="print more information, warnings, and error messages")

    op.add_option("--tail", dest="tail", type="int", metavar="<NUM>", default=0,
                  help="print only the last NUM number of telegrams")

    options, args = op.parse_args()

    #print options
    #print groupAddrs
    #print types
    #sys.exit(1)

    verbose = options.verbose
    
    # All output variants will likly support utf-8...
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout)

    knx = KnxLogViewer("enheter.xml", "groupaddresses.csv",
                       options.infilenames, options.dumpGAtable,
                       types, options.flanksOnly, options.tail)

    if options.plot:
        knx.plotLog(groupAddrs, "")
    else:
        knx.printLog(groupAddrs)


# All temperatures:
# python knxmonitor_decoder.py -i knx_log.hex.1 -i knx_log.hex.1  -g 1/3/1 temp -g 1/3/0 temp  -g 1/3/5 temp  -g 2/3/0 temp  -g 2/3/1 temp   -g 2/3/2 temp -g 3/2/0 temp -p


# Bad 2 etg
# python knxmonitor_decoder.py -i knx_log.hex.1 -i knx_log.hex  -g 2/6/0 % -g 2/3/0 temp -g 3/2/0 temp -f -p

