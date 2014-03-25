import sys,traceback
import os
import time
import shutil
import json
import logging
import hltdconf


ES_DIR_NAME = "TEMP_ES_DIRECTORY"
UNKNOWN,JSD,STREAM,INDEX,FAST,SLOW,OUTPUT,INI,EOLS,EOR,DAT,PDAT,CRASH = range(13)            #file types 
TO_ELASTICIZE = [STREAM,INDEX,OUTPUT,EOR]
MONBUFFERSIZE = 50



#Output redirection class
class stdOutLog:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)    
    def write(self, message):
        self.logger.debug(message)
class stdErrorLog:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    def write(self, message):
        self.logger.error(message)





class fileHandler(object):
    def __eq__(self,other):
        return self.filepath == other.filepath

    def __getattr__(self,name):
        if name not in self.__dict__: 
            if name in ["dir","ext","basename","name"]: self.getFileInfo() 
            elif name in ["filetype"]: self.filetype = self.getFiletype();
            elif name in ["run","ls","stream","index","pid"]: self.getFileHeaders()
            elif name in ["data"]: self.data = self.getJsonData(); 
            elif name in ["definitions"]: self.getDefinitions()
            elif name in ["host"]: self.host = os.uname()[1];
        return self.__dict__[name]

    def __init__(self,filepath):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.filepath = filepath
        self.outDir = self.dir

        
    def getFileInfo(self):
        self.dir = os.path.dirname(self.filepath)
        self.basename = os.path.basename(self.filepath)
        self.name,self.ext = os.path.splitext(self.basename)

    def getFiletype(self,filepath = None):
        if not filepath: filepath = self.filepath
        filename = self.basename
        name,ext = self.name,self.ext
        name = name.upper()
        if "mon" not in filepath:
            if ext == ".dat" and "PID" not in name: return DAT
            if ext == ".dat" and "PID" in name: return PDAT
            if ext == ".ini" and "PID" in name: return INI
            if ext == ".jsd" and "OUTPUT" in name: return JSD
            if ext == ".jsn":
                if "STREAM" in name and "PID" in name: return STREAM
                if "STREAM" in name and "PID" not in name: return OUTPUT
                elif "INDEX" in name and  "PID" in name: return INDEX
                elif "CRASH" in name and "PID" in name: return CRASH
                elif "EOLS" in name: return EOLS
                elif "EOR" in name: return EOR
        if ".fast" in filename: return FAST
        if "slow" in filename: return SLOW
        return UNKNOWN


    def getFileHeaders(self):
        filetype = self.filetype
        name,ext = self.name,self.ext
        splitname = name.split("_")
        if filetype in [STREAM,INI,PDAT,CRASH]: self.run,self.ls,self.stream,self.pid = splitname
        elif filetype in [DAT,OUTPUT]: self.run,self.ls,self.stream,self.host = splitname
        elif filetype == INDEX: self.run,self.ls,self.index,self.pid = splitname
        elif filetype == EOLS: self.run,self.ls,self.eols = splitname
        else: 
            self.logger.warning("Bad filetype: %s" %self.filepath)
            self.run,self.ls,self.stream = [None]*3


        #get data from json file
    def getJsonData(self,filepath = None):
        if not filepath: filepath = self.filepath
        try:
            with open(filepath) as fi:
                data = json.load(fi)
        except StandardError,e:
            self.logger.exception(e)
            data = {}
        return data

    def setJsdfile(self,jsdfile):
        self.jsdfile = jsdfile
        if self.filetype in [OUTPUT,CRASH]: self.initData()
        
    def initData(self):
        defs = self.definitions
        self.data = {}
        if defs:
            self.data["data"] = [self.nullValue(f["type"]) for f in defs]

    def nullValue(self,ftype):
        if ftype == "integer": return 0
        elif ftype  == "string": return ""
        else: 
            self.logger.warning("bad field type %r" %(ftype))
            return "ERR"

    def checkSources(self):
        data,defs = self.data,self.definitions
        for item in defs:
            fieldName = item["name"]
            index = defs.index(item)
            if "source" in item: 
                source = item["source"]
                sIndex,ftype = self.getFieldIndex(field)
                data[index] = data[sIndex]

    def getFieldIndex(self,field):
        defs = self.definitions
        if defs: 
            index = next((defs.index(item) for item in defs if item["name"] == field),-1)
            ftype = defs[index]["type"]
            return index,ftype

        
    def getFieldByName(self,field):
        index,ftype = self.getFieldIndex(field)
        data = self.data["data"]
        if index > -1:
            value = int(data[index]) if ftype == "integer" else str(data[index]) 
            return value
        else:
            self.logger.warning("bad field request %r in %r" %(field,self.definitions))
            return False

    def setFieldByName(self,field,value):
        index,ftype = self.getFieldIndex(field)
        data = self.data["data"]
        if index > -1:
            data[index] = value
            return True
        else:
            self.logger.warning("bad field request %r in %r" %(field,self.definitions))
            return False

        #get definitions from jsd file
    def getDefinitions(self):
        if self.filetype == STREAM:
            self.jsdfile = self.data["definition"]
        elif not self.jsdfile: 
            self.logger.warning("jsd file not set")
            self.definitions = {}
            return False
        self.definitions = self.getJsonData(self.jsdfile)["data"]
        return True


    def deleteFile(self):
        filepath = self.filepath
        self.logger.info(filepath)
        if os.path.isfile(filepath):
            try:
                self.esCopy()
                os.remove(filepath)
            except Exception,e:
                self.logger.exception(e)
                return False
        return True

    def moveFile(self,newpath,copy = False):
        oldpath = self.filepath
        newdir = os.path.dirname(newpath)

        if not os.path.exists(oldpath): return False

        self.logger.info("%s -> %s" %(oldpath,newpath))
        try:
            if not os.path.isdir(newdir): os.makedirs(newdir)
            if copy: shutil.copy(oldpath,newpath)
            else: 
                self.esCopy()
                shutil.move(oldpath,newpath)
        except OSError,e:
            self.logger.exception(e)
            return False
        self.filepath = newpath
        self.getFileInfo()
        return True   


    def exists(self):
        return os.path.exists(self.filepath)

        #write self.outputData in json self.outputFile
    def writeout(self):
        filepath = self.filepath
        outputData = self.data
        self.logger.info(filepath)
        try:
            with open(filepath,"w") as fi: 
                json.dump(outputData,fi)
        except Exception,e:
            self.logger.exception(e)
            return False
        return True

    def esCopy(self):
        if self.filetype in TO_ELASTICIZE:
            esDir = os.path.join(self.dir,ES_DIR_NAME)
            self.logger.debug(esDir)
            if os.path.isdir(esDir):
                newpath = os.path.join(esDir,self.basename)
                shutil.copy(self.filepath,newpath)


    def merge(self,infile):
        defs,oldData = self.definitions,self.data["data"][:]           #TODO: check infile definitions 
        jsdfile = infile.jsdfile
        host = infile.host
        newData = infile.data["data"][:]

        self.logger.debug("old: %r with new: %r" %(oldData,newData))
        result=Aggregator(defs,oldData,newData).output()
        self.logger.debug("result: %r" %result)
        self.data["data"] = result
        self.data["definition"] = jsdfile
        self.data["source"] = host
        self.writeout()





class Aggregator(object):
    def __init__(self,definitions,newData,oldData):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.definitions = definitions
        self.newData = newData
        self.oldData = oldData

    def output(self):
        self.result = map(self.action,self.definitions,self.newData,self.oldData)
        return self.result

    def action(self,definition,data1,data2=None):
        actionName = "action_"+definition["operation"] 
        if hasattr(self,actionName):
            try:
                return getattr(self,actionName)(data1,data2)
            except AttributeError,e:
                self.logger.exception(e)
                return None
        else:
            self.logger.warning("bad operation: %r" %actionName)
            return None

    def action_binaryOr(self,data1,data2):
        try:
            res =  int(data1) | int(data2)
        except TypeError,e:
            self.logger.exception(e)
            res = 0
        return str(res)

    def action_merge(self,data1,data2):
        if not data2: return data1
        file1 = fileHandler(data1)
        
        file2 = fileHandler(data2)
        newfilename = "_".join([file2.run,file2.ls,file2.stream,file2.host])+file2.ext
        file2 = fileHandler(newfilename)

        if not file1 == file2:
            if data1: self.logger.warning("found different files: %r,%r" %(file1.filepath,file2.filepath))
            return file2.basename
        return file1.basename


    def action_sum(self,data1,data2):
        try:
            res =  int(data1) + int(data2)
        except TypeError,e:
            self.logger.exception(e)
            res = 0
        return str(res)

    def action_same(self,data1,data2):
        if str(data1) == str(data2):
            return str(data1)
        else:
            return "N/A"
        
    def action_cat(self,data1,data2):
        if data2: return str(data1)+","+str(data2)
        else: return str(data1)