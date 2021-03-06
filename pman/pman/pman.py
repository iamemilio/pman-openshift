#!/usr/bin/env python3.5
# -*- coding: utf-8 -*-

import  abc
#import  sys
import  time
import  os

import  threading
import  zmq
#from    zmq.devices     import ProcessDevice
from    webob           import  Response
import  psutil

import  queue
from    functools       import  partial
import  platform

import  multiprocessing

import  pudb


# pman local dependencies
from   ._colors           import Colors
from   .crunner           import crunner
from   .C_snode           import *
from   .debug             import debug
from   .pfioh             import *


class StoppableThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition."""

    def __init__(self, *args, **kwargs):
        super(StoppableThread, self).__init__(*args, **kwargs)
        self._stopper = threading.Event()

    def stopit(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.isSet()

class pman(object):
    """
    The server class for the pman (process manager) server

    """
    __metaclass__   = abc.ABCMeta

    def col2_print(self, str_left, str_right):
        self.dp.qprint(Colors.WHITE +
              ('%*s' % (self.LC, str_left)), end='')
        self.dp.qprint(Colors.LIGHT_BLUE +
              ('%*s' % (self.RC, str_right)) + Colors.NO_COLOUR)

    def __init__(self, **kwargs):
        """
        Constructor
        """
        self.within             = None                      # An encapsulating object

        # Description
        self.str_desc           = ""

        # The main server function
        self.threaded_server    = None

        # The listener thread array -- each element of this array is threaded listener
        # object
        self.l_listener         = []
        self.listenerSleep      = 0.1

        # The fileIO threaded object
        self.fileIO             = None

        # DB
        self.b_clearDB          = False
        self.str_DBpath         = '/tmp/pman'
        self._ptree             = C_stree()
        self.str_fileio         = 'json'

        # Comms
        self.str_protocol       = "tcp"
        self.str_IP             = "127.0.0.1"
        self.str_port           = "5010"
        self.router_raw         = 0
        self.listeners          = 1
        self.b_http             = False

        # Job info
        self.auid               = ''
        self.jid                = ''

        # Debug parameters
        self.str_debugFile      = '/dev/null'
        self.b_debugToFile      = True

        for key,val in kwargs.items():
            if key == 'protocol':       self.str_protocol   = val
            if key == 'IP':             self.str_IP         = val
            if key == 'port':           self.str_port       = val
            if key == 'raw':            self.router_raw     = int(val)
            if key == 'listeners':      self.listeners      = int(val)
            if key == 'listenerSleep':  self.listenerSleep  = float(val)
            if key == 'http':           self.b_http         = int(val)
            if key == 'within':         self.within         = val
            if key == 'debugFile':      self.str_debugFile  = val
            if key == 'debugToFile':    self.b_debugToFile  = val
            if key == 'DBpath':         self.str_DBpath     = val
            if key == 'clearDB':        self.b_clearDB      = val
            if key == 'desc':           self.str_desc       = val

        # pudb.set_trace()

        # Screen formatting
        self.LC                 = 30
        self.RC                 = 50
        self.dp                 = debug(    verbosity   = 0,
                                            level       = -1,
                                            debugFile   = self.str_debugFile,
                                       
     debugToFile = self.b_debugToFile)

        if self.b_clearDB and os.path.isdir(self.str_DBpath):
            shutil.rmtree(self.str_DBpath)

        print(self.str_desc)

        # self.dp.qprint(Colors.YELLOW)
        # self.dp.qprint("""
        # \t+-----------------------------------------------+
        # \t| Welcome to the pman process management system |
        # \t+-----------------------------------------------+
        # """)
        # self.dp.qprint(Colors.CYAN + """
        # 'pman' is a client/server system that allows users to monitor
        # and control processes on (typically) Linux systems. Actual
        # processes are spawned using the 'crunner' module and as such
        # are ssh and HPC aware.
        #
        # The 'pman' server can be queried for running processes, lost/dead
        # processes, exit status, etc.
        #
        # Communication from the 'pman' server is via JSON constructs. See the
        # github page for more information.
        #
        # Typical calling syntax is:
        #
        #         ./pman.py   --raw 1                 \\
        #                     --http                  \\
        #                     --ip <someIP>           \\
        #                     --port 5010             \\
        #                     --listeners <listeners>
        #
        # """)

        # pudb.set_trace()
        self.col2_print('Server is listening on',
                        '%s://%s:%s' % (self.str_protocol, self.str_IP, self.str_port))
        self.col2_print('Router raw mode',                  str(self.router_raw))
        self.col2_print('HTTP response back mode',          str(self.b_http))
        self.col2_print('listener sleep',                   str(self.listenerSleep))

        # Read the DB from HDD
        self._ptree             = C_stree()
        # self.DB_read()
        self.DB_fileIO(cmd = 'load')

        # Setup zmq context
        self.zmq_context        = zmq.Context()

    def DB_read(self, **kwargs):
        """
        Read the DB from filesystem. If DB does not exist on filesystem,
        create an empty DB and save to filesystem.
        """
        if os.path.isdir(self.str_DBpath):
            self.dp.qprint("Reading pman DB from disk...\n")
            self._ptree = C_stree.tree_load(
                pathDiskRoot    = self.str_DBpath,
                loadJSON        = True,
                loadPickle      = False)
            self.dp.qprint("pman DB read from disk...\n")
            self.col2_print('Reading pman DB from disk:', 'OK')
        else:
            P = self._ptree
            # P.cd('/')
            # P.mkdir('proc')
            P.tree_save(
                startPath       = '/',
                pathDiskRoot    = self.str_DBpath,
                failOnDirExist  = False,
                saveJSON        = True,
                savePickle      = False
            )
            self.col2_print('Reading pman DB from disk:',
                            'No DB found... creating empty default DB')
        self.dp.qprint(Colors.NO_COLOUR, end='')

    def DB_fileIO(self, **kwargs):
        """
        Process DB file IO requests. Typically these control the
        DB -- save or load.
        """
        str_cmd     = 'save'
        str_DBpath  = self.str_DBpath
        str_fileio  = 'json'
        tree_DB     = self._ptree

        for k,v in kwargs.items():
            if k == 'cmd':      str_cmd             = v
            if k == 'fileio':   self.str_fileio     = v
            if k == 'dbpath':   str_DBpath          = v
            if k == 'db':       tree_DB             = v

        self.dp.qprint('cmd      = %s' % str_cmd)
        self.dp.qprint('fileio   = %s' % self.str_fileio)
        self.dp.qprint('dbpath   = %s' % str_DBpath)

        if str_cmd == 'save':
            if os.path.isdir(str_DBpath):
                shutil.rmtree(str_DBpath)
            #print(tree_DB)
            if self.str_fileio   == 'json':
                tree_DB.tree_save(
                    startPath       = '/',
                    pathDiskRoot    = str_DBpath,
                    failOnDirExist  = False,
                    saveJSON        = True,
                    savePickle      = False)
            if self.str_fileio   == 'pickle':
                tree_DB.tree_save(
                    startPath       = '/',
                    pathDiskRoot    = str_DBpath,
                    failOnDirExist  = False,
                    saveJSON        = False,
                    savePickle      = True)

        if str_cmd == 'load':
            if os.path.isdir(str_DBpath):
                self.dp.qprint("Reading pman DB from disk...\n")
                if self.str_fileio   == 'json':
                    tree_DB = C_stree.tree_load(
                        startPath       = '/',
                        pathDiskRoot    = str_DBpath,
                        failOnDirExist  = False,
                        loadJSON        = True,
                        loadPickle      = False)
                if self.str_fileio   == 'pickle':
                    tree_DB = C_stree.tree_load(
                        startPath       = '/',
                        pathDiskRoot    = str_DBpath,
                        failOnDirExist  = False,
                        loadJSON        = False,
                        loadPickle      = True)
                self.dp.qprint("pman DB read from disk...\n")
                self.col2_print('Reading pman DB from disk:', 'OK')
                self._ptree         = tree_DB
            else:
                tree_DB.tree_save(
                    startPath       = '/',
                    pathDiskRoot    = str_DBpath,
                    failOnDirExist  = False,
                    saveJSON        = True,
                    savePickle      = False
                )
                self.col2_print('Reading pman DB from disk:',
                                'No DB found... creating empty default DB')
            self.dp.qprint(Colors.NO_COLOUR, end='')

    def thread_serve(self):
        """
        Serve the 'start' method in a thread.
        :return:
        """
        self.threaded_server  = StoppableThread(target=self.start)
        self.threaded_server.start()

        while not self.threaded_server.stopped():
            time.sleep(1)

        # Stop the listeners...
        self.dp.qprint("setting b_stopThread on all listeners...")
        for i in range(0, self.listeners):
            self.dp.qprint("b_stopThread on listener %d and executing join()..." % i)
            self.l_listener[i].b_stopThread = True
            self.l_listener[i].join()

        # Stop the fileIO
        self.fileIO.b_stopThread    = True
        self.dp.qprint("b_stopThread on fileIO executing join()...")
        self.fileIO.join()

        self.dp.qprint("Shutting down the zmq infrastructure...")
        try:
            self.dp.qprint('calling self.socket_back.close()')
            self.socket_back.close()
        except:
            self.dp.qprint('Caught exception in closing back socket')

        try:
            self.dp.qprint('calling self.socket_front.close()')
            self.socket_front.close()
        except zmq.error.ZMQError:
            self.dp.qprint('Caught exception in closing front socket...')

        self.dp.qprint('calling zmq_context.term()')
        # self.zmq_context.term()

        self.dp.qprint("calling join() on all this thread...")
        self.threaded_server.join()
        self.dp.qprint("shutdown successful...")

    def start(self):
        """
            Main execution.

            * Instantiate several 'listener' worker threads
                **  'listener' threads are used to process input from external
                    processes. In turn, 'listener' threads can thread out
                    'crunner' threads that actually "run" the job.
            * Instantiate a job poller thread
                **  'poller' examines the internal DB entries and regularly
                    queries the system process table, tracking if jobs
                    are still running.
        """

        self.col2_print('Starting Listener threads', self.listeners)

        # Front facing socket to accept client connections.
        self.socket_front = self.zmq_context.socket(zmq.ROUTER)
        self.socket_front.router_raw = self.router_raw
        self.socket_front.setsockopt(zmq.LINGER, 1)
        self.socket_front.bind('%s://%s:%s' % (self.str_protocol,
                                          self.str_IP,
                                          self.str_port)
                          )

        # Backend socket to distribute work.
        self.socket_back = self.zmq_context.socket(zmq.DEALER)
        self.socket_back.setsockopt(zmq.LINGER, 1)
        self.socket_back.bind('inproc://backend')

        # Start the 'fileIO' thread
        self.fileIO      = FileIO(      timeout     = 60,
                                        within      = self,
                                        debugFile   = self.str_debugFile,
                                        debugToFile = self.b_debugToFile)
        self.fileIO.start()

        # Start the 'listener' workers... keep track of each
        # listener instance so that we can selectively stop
        # them later.
        for i in range(0, self.listeners):
            self.l_listener.append(Listener(
                                    id              = i,
                                    context         = self.zmq_context,
                                    DB              = self._ptree,
                                    DBpath          = self.str_DBpath,
                                    http            = self.b_http,
                                    within          = self,
                                    listenerSleep   = self.listenerSleep,
                                    debugToFile     = self.b_debugToFile,
                                    debugFile       = self.str_debugFile))
            self.l_listener[i].start()

        # Use built in queue device to distribute requests among workers.
        # What queue device does internally is,
        #   1. Read a client's socket ID and request.
        #   2. Send socket ID and request to a worker.
        #   3. Read a client's socket ID and result from a worker.
        #   4. Route result back to the client using socket ID.
        self.dp.qprint("*******before  zmq.device!!!")
        try:
            zmq.device(zmq.QUEUE, self.socket_front, self.socket_back)
        except:
            self.dp.qprint('Hmmm... some error was caught on shutting down the zmq.device...')
        self.dp.qprint("*******after zmq.device!!!")

    def __iter__(self):
        yield('Feed', dict(self._stree.snode_root))

    # @abc.abstractmethod
    # def create(self, **kwargs):
    #     """Create a new tree
    #
    #     """

    def __str__(self):
        """Print
        """
        return str(self.stree.snode_root)

    @property
    def stree(self):
        """STree Getter"""
        return self._stree

    @stree.setter
    def stree(self, value):
        """STree Getter"""
        self._stree = value

class FileIO(threading.Thread):
    """
    A class that periodically saves the database from memory out to disk.
    """

    def __init__(self, **kwargs):
        self.__name             = "FileIO"
        self.b_http             = False

        self.str_DBpath         = "/tmp/pman"

        self.timeout            = 60
        self.within             = None

        self.b_stopThread       = False

        # Debug parameters
        self.str_debugFile      = '/dev/null'
        self.b_debugToFile      = True

        for key,val in kwargs.items():
            if key == 'DB':             self._ptree         = val
            if key == 'DBpath':         self.str_DBpath     = val
            if key == 'timeout':        self.timeout        = val
            if key == 'within':         self.within         = val
            if key == 'debugFile':      self.str_debugFile  = val
            if key == 'debugToFile':    self.b_debugToFile  = val

        self.dp                 = debug(verbosity   = 0,
                                        level       = -1,
                                        debugFile   = self.str_debugFile,
                                        debugToFile = self.b_debugToFile)


        threading.Thread.__init__(self)

    def run(self):
        """ Main execution. """
        # pudb.set_trace()
        # Socket to communicate with front facing server.
        while not self.b_stopThread:
            # self.dp.qprint('Saving DB as type "%s" to "%s"...' % (
            #     self.within.str_fileio,
            #     self.within.str_DBpath
            # ))
            self.within.DB_fileIO(cmd = 'save')
            # self.dp.qprint('DB saved...')
            for second in range(0, self.timeout):
                if not self.b_stopThread:
                    time.sleep(1)
                else:
                    break

        self.dp.qprint('returning from FileIO run method...')
        # raise ValueError('FileIO thread terminated.')

class Listener(threading.Thread):
    """ Listeners accept communication requests from front facing server.
        Parse input text streams and act accordingly. """

    def __init__(self, **kwargs):
        self.__name             = "Listener"
        self.b_http             = False

        self.poller             = None
        self.str_DBpath         = "/tmp/pman"
        self.str_jobRootDir     = ''

        self.listenerSleep      = 0.1

        self.jid                = ''
        self.auid               = ''

        self.within             = None
        self.b_stopThread       = False

        # Debug parameters
        self.str_debugFile      = '/dev/null'
        self.b_debugToFile      = True

        for key,val in kwargs.items():
            if key == 'context':        self.zmq_context    = val
            if key == 'listenerSleep':  self.listenerSleep  = float(val)
            if key == 'id':             self.worker_id      = val
            if key == 'DB':             self._ptree         = val
            if key == 'DBpath':         self.str_DBpath     = val
            if key == 'http':           self.b_http         = val
            if key == 'within':         self.within         = val
            if key == 'debugFile':      self.str_debugFile  = val
            if key == 'debugToFile':    self.b_debugToFile  = val

        self.dp                 = debug(verbosity   = 0,
                                        level       = -1,
                                        debugFile   = self.str_debugFile,
                                        debugToFile = self.b_debugToFile)

        threading.Thread.__init__(self)
        # logging.debug('leaving __init__')

    def run(self):
        """ Main execution. """
        # Socket to communicate with front facing server.
        self.dp.qprint('starting...')
        socket = self.zmq_context.socket(zmq.DEALER)
        socket.connect('inproc://backend')

        b_requestWaiting        = False
        resultFromProcessing    = False
        request                 = ""
        client_id               = -1
        self.dp.qprint(Colors.BROWN + "Listener ID - %s: run() - Ready to serve..." % self.worker_id)
        while not self.b_stopThread:

            # wait (non blocking) for input on socket
            try:
                client_id, request  = socket.recv_multipart(flags = zmq.NOBLOCK)
                self.dp.qprint('Received %s from client_id: %s' % (request, client_id))
                b_requestWaiting    = True
            except zmq.Again as e:
                if self.listenerSleep:
                    time.sleep(0.1)
                else:
                    pass

            if b_requestWaiting:
                self.dp.qprint(Colors.BROWN + 'Listener ID - %s: run() - Received comms from client.' % (self.worker_id))
                self.dp.qprint(Colors.BROWN + 'Client sends: %s' % (request))

                resultFromProcessing    = self.process(request)
                if resultFromProcessing:
                    self.dp.qprint(Colors.BROWN + 'Listener ID - %s: run() - Sending response to client.' %
                                   (self.worker_id))
                    self.dp.qprint('JSON formatted response:')
                    str_payload = json.dumps(resultFromProcessing)
                    self.dp.qprint(Colors.LIGHT_CYAN + str_payload)
                    self.dp.qprint(Colors.BROWN + 'len = %d chars' % len(str_payload))
                    socket.send(client_id, zmq.SNDMORE)
                    if self.b_http:
                        str_contentType = "application/json"
                        res  = Response(str_payload)
                        res.content_type = str_contentType

                        str_HTTPpre = "HTTP/1.x "
                        str_res     = "%s%s" % (str_HTTPpre, str(res))
                        str_res     = str_res.replace("UTF-8", "UTF-8\nAccess-Control-Allow-Origin: *")

                        socket.send(str_res.encode())
                    else:
                        socket.send(str_payload)
            b_requestWaiting    = False
        self.dp.qprint('Listnener ID - %s: Returning from run()...' % self.worker_id)
        # raise('Listener ID - %s: Thread terminated' % self.worker_id)
        return True

    def t_search_process(self, *args, **kwargs):
        """

        Search

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In search process...")

        d_request   = {}
        d_ret       = {}
        hits        = 0

        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_meta          = d_request['meta']

        b_pathSpec      = False
        str_path        = ""
        if 'path' in d_meta:
            b_pathSpec  = True
            str_path    = d_meta['path']

        b_jobSpec       = False
        str_jobSpec    = ""
        if 'job' in d_meta:
            b_jobSpec   = True
            str_jobSpec = d_meta['job']

        b_fieldSpec    = False
        str_fieldSpec  = ""
        if 'field' in d_meta:
            b_fieldSpec = True
            str_fieldSpec = d_meta['field']

        b_whenSpec      = False
        str_whenSpec    = "end"
        if 'when' in d_meta:
            b_whenSpec = True
            str_whenSpec = d_meta['when']

        self.dp.qprint(d_meta)
        self.dp.qprint(b_pathSpec)
        str_fileName    = d_meta['key']
        str_target      = d_meta['value']
        p               = self._ptree
        str_origDir     = p.cwd()
        str_pathOrig    = str_path
        for r in self._ptree.lstr_lsnode('/'):
            if p.cd('/' + r)['status']:
                str_val = p.cat(str_fileName)
                if str_val == str_target:
                    if not b_pathSpec:
                        str_path            = '/api/v1/' + r + '/' + str_fileName
                    else:
                        str_path            = '/api/v1/' + r + str_pathOrig
                        if str_path[-1] == '/': str_path = str_path[:-1]
                    if b_jobSpec:
                        str_path            = '/api/v1/' + r +              '/' + \
                                                str_whenSpec +              '/' + \
                                                str_jobSpec +               '/' + \
                                                '%sInfo' % str_whenSpec +   '/' + \
                                                str_jobSpec +               '/' + \
                                                str_fieldSpec
                    d_ret[str(hits)]    = {}
                    d_ret[str(hits)]    = self.DB_get(path = str_path)
                    hits               += 1
        p.cd(str_origDir)

        return {"d_ret":    d_ret,
                "status":   bool(hits)}

    def t_info_process(self, *args, **kwargs):
        """

        Check if the job corresponding to the search pattern is "done".

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In info process...")

        d_request   = {}
        d_ret       = {}
        b_status    = False
        hits        = 0
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_search    = self.t_search_process(request = d_request)['d_ret']

        p = self._ptree
        for j in d_search.keys():
            d_j = d_search[j]
            for job in d_j.keys():
                str_pathStart       = '/api/v1/' + job + '/startInfo'
                str_pathEnd         = '/api/v1/' + job + '/endInfo'
                d_ret[str(hits)+'.0']    = {}
                d_ret[str(hits)+'.0']    = self.DB_get(path = str_pathStart)
                d_ret[str(hits)+'.1']    = {}
                d_ret[str(hits)+'.1']    = self.DB_get(path = str_pathEnd)
                hits               += 1
        if not hits:
            d_ret                   = {
                "-1":   {
                    "noJobFound":   {
                        "endInfo":  {"allJobsDone": None}
                    }
                }
            }
        else:
            b_status            = True
        return {"d_ret":    d_ret,
                "status":   b_status}

    def t_quit_process(self, *args, **kwargs):
        """
        Process the 'quit' POST directive. This might appear counter-inuitive
        at first glance since the 'get' is the result of a REST POST, but is
        logically consistent within the semantics of this system.
        """
        d_request   = {}
        d_ret       = {}
        b_status    = False
        hits        = 0
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v
        d_meta      = d_request['meta']
        if 'saveDB' in d_meta.keys():
            self.dp.qprint("Saving DB...")
            self.within.DB_fileIO(cmd = 'save')

        self.dp.qprint('calling threaded_server.stop()')
        self.within.threaded_server.stopit()
        self.dp.qprint('called threaded_server.stop()')

        return {'d_ret':    d_ret,
                'status':   True}

    def t_get_process(self, *args, **kwargs):
        """
        Process the 'get' POST directive. This might appear counter-inuitive
        at first glance since the 'get' is the result of a REST POST, but is
        logically consistent within the semantics of this system.
        """
        d_request   = {}
        d_ret       = {}
        b_status    = False
        hits        = 0
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v
        d_meta      = d_request['meta']
        str_path    = '/api/v1' + d_meta['path']
        d_ret       = self.DB_get(path  = str_path)
        return {'d_ret':    d_ret,
                'status':   True}

    def t_fileiosetup_process(self, *args, **kwargs):
        """
        Setup a thread with a socket listener. Return listener address to client
        """
        self.dp.qprint("In fileiosetup process...")

        d_ret               = {}
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_meta  = d_request['meta']

        d_ret['fileioIP']   = "%s" % self.within.str_IP
        d_ret['fileioport'] = "%s" % (int(self.within.str_port) + self.worker_id)
        d_ret['serveforever']=d_meta['serveforever']

        d_args              = {}
        d_args['ip']        = d_ret['fileioIP']
        d_args['port']      = d_ret['fileioport']

        server              = ThreadedHTTPServer((d_args['ip'], int(d_args['port'])), StoreHandler)
        server.setup(args   = d_args)
        self.dp.qprint("serveforever = %d" % d_meta['serveforever'])
        b_serveforever      = False
        if 'serveforever' in d_meta.keys():
            b_serveforever  = d_meta['serveforever']

        if b_serveforever:
            self.dp.qprint("about to serve_forever()...")
            server.serve_forever()
        else:
            self.dp.qprint("about to handle_request()...")
            server.handle_request()

        return {"d_ret":    d_ret,
                "status":   True}

    def job_state(self, *args, **kwargs):
        """

        Return a structure that can be further processed to determine the job's state.

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In done process...")

        d_request   = {}
        d_ret       = {}
        b_status    = False
        hits        = 0
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_search    = self.t_search_process(request = d_request)['d_ret']

        p   = self._ptree
        Ts  = C_stree()
        Te  = C_stree()
        for j in d_search.keys():
            d_j = d_search[j]
            for job in d_j.keys():
                str_pathStart       = '/api/v1/' + job + '/start'
                str_pathEnd         = '/api/v1/' + job + '/end'
                str_jobStart        = '/' + job + '/start'
                str_jobEnd          = '/' + job + '/end'

                d_start             = self.DB_get(path = str_pathStart)
                d_end               = self.DB_get(path = str_pathEnd)
                Ts.initFromDict(d_start)
                Te.initFromDict(d_end)

                # self.DB_get(path = str_pathStart).copy(startPath = '/', destination = Ts)
                # self.DB_get(path = str_pathEnd).copy(startPath = '/',   destination = Te)

                # pudb.set_trace()

                # print('Ts startPath = %s' % str_pathStart)
                # print('Te startPath = %s' % str_pathEnd)

                # p.tree_copy(startPath = str_jobStart,   destination = Ts)
                # p.tree_copy(startPath = str_jobEnd,     destination = Te)

                self.dp.qprint("Ts.cwd = %s " % Ts.cwd())
                self.dp.qprint(Ts)
                self.dp.qprint("Te.cwd = %s " % Te.cwd())
                self.dp.qprint(Te)

                l_subJobsStart      = []
                if Ts.cd('/%s/start' % job)['status']:
                    l_subJobsStart  = Ts.lstr_lsnode()
                    l_subJobsStart  = list(map(int, l_subJobsStart))
                    l_subJobsStart.sort()
                    self.dp.qprint("l_subJobsStart  (pre) = %s" % l_subJobsStart)
                    if len(l_subJobsStart) > 1: l_subJobsStart  = l_subJobsStart[:-1]

                l_subJobsEnd        = []
                if Te.cd('/%s/end' % job)['status']:
                    l_subJobsEnd    = Te.lstr_lsnode()
                    l_subJobsEnd    = list(map(int, l_subJobsEnd))
                    l_subJobsEnd.sort()
                    self.dp.qprint("l_subJobsEnd    (pre) = %s " % l_subJobsEnd)
                    if len(l_subJobsEnd) > 1: l_subJobsEnd    = l_subJobsEnd[:-1]

                self.dp.qprint("l_subJobsStart (post) = %s" % l_subJobsStart)
                self.dp.qprint("l_subJobsEnd   (post) = %s" % l_subJobsEnd)

                for j in l_subJobsStart:
                    l_subJobsStart[j]   = Ts.cat('/%s/start/%d/startInfo/%d/startTrigger' % \
                                                 (job, j, j))

                # jobsEnd behaviour can be slightly different to the jobStart, particularly if
                # the job being executed is killed -- sometimes recording the "death" event of
                # the job does not happen and the job indexing ends up missing several epochs:
                #
                #           l_subJobsStart  (pre) = [0, 1, 2, 3, 4]
                #           l_subJobsEnd    (pre) = [0, 1, 3, 4]
                #
                # to assure correct returncode lookup, we always parse the latest job epoch.

                latestJob       = 0
                if len(l_subJobsEnd):
                    latestJob   = l_subJobsEnd[-1]
                    for j in list(range(0, latestJob+1)):
                        l_subJobsEnd[j]     = Te.cat('/%s/end/%s/endInfo/%d/returncode' % (job, latestJob, j))

                d_ret[str(hits)+'.start']   = {"jobRoot": job, "startTrigger":  l_subJobsStart}
                d_ret[str(hits)+'.end']     = {"jobRoot": job, "returncode":    l_subJobsEnd}
                hits               += 1
        if not hits:
            d_ret                   = {
                "-1":   {
                    "noJobFound":   {
                        "endInfo":  {"allJobsDone": None}
                    }
                }
            }
        else:
            b_status            = True
        return {"d_ret":    d_ret,
                "status":   b_status}


    def t_done_process(self, *args, **kwargs):
        """

        Check if the job corresponding to the search pattern is "done".

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In done process...")

        return self.job_state(*args, **kwargs)


    def t_status_process(self, *args, **kwargs):
        """

        Return status on a given job.

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In status process...")

        d_state     = self.job_state(*args, **kwargs)

        d_ret       = d_state['d_ret']
        b_status    = d_state['status']

        l_keys      = d_ret.items()
        l_status    = []
        for i in range(0, int(len(l_keys)/2)):
            b_startEvent    = d_ret['%s.start'  % str(i)]['startTrigger'][0]
            try:
                endcode     = d_ret['%s.end'    % str(i)]['returncode'][0]
            except:
                endcode     = None

            if endcode == None and b_startEvent:
                l_status.append('started')
            if not endcode and b_startEvent and type(endcode) is int:
                l_status.append('finishedSuccessfully')
            if endcode and b_startEvent:
                l_status.append('finishedWithError')

            self.dp.qprint('b_startEvent = %d' % b_startEvent)
            self.dp.qprint(endcode)
            self.dp.qprint('l_status = %s' % l_status)

        d_ret['l_status']   = l_status
        return {"d_ret":    d_ret,
                "status":   b_status}

    def t_openshift_process(self, *args, **kwargs):
        """
        The openshift process initiates an openshift job by calling the openshift.py class.
        This is used to launch jobs within the openshift cluster. 
        """

        self.dp.qprint("In hello process...")
        b_status            = False
        d_ret               = {}
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_meta          = d_request['meta']

        #specify parameters here ---> pass them in meta json payload
        #these parameters should match the inputs for the openshift-manager.py class, as well as the needs for the pman process manager.
        """
        Current meta params:  modeled after the run command
            jid: a unique ID assigned to a job
            auid: Authorized user id. Id of the user requesting the job.
            cmd: The name of the command you intend to run.
        """
        if d_meta:
            if 'jid' in d_meta.keys() and 'auid' in d_meta.keys() and 'cmd' in d_meta.keys():
                self.jid    = d_meta['jid']
                self.auid   = d_meta['auid']
                self.str_cmd     = d_meta['cmd']
            else:
                self.dp.qprint("Process Failed! Insufficient or incorrect meta parameters!")
                return {"d_ret":    d_ret,
                        "status":   b_status}
            
            #launch openshiftController container here 
            


            #poll status of container until docker ps -a shows it running


            
            #if job succesful
            '''
            to make a dictionary object as a return parameter
            d_ret['x'] = {}  
            
            to add parameters to that dictionary object
            d_ret['x']['y'] = what to return on lookup of x,y in system
            
            '''
            b_status = True
            return {"d_ret":    d_ret,
                    "status":   b_status}



    def t_hello_process(self, *args, **kwargs):
        """
        The 'hello' action is merely to 'speak' with the server. The server
        can return current date/time, echo back a string, query the startup
        command line args, etc.

        This method is a simple means of checking if the server is "up" and
        running.

        :param args:
        :param kwargs:
        :return:
        """

        self.dp.qprint("In hello process...")
        b_status            = False
        d_ret               = {}
        for k, v in kwargs.items():
            if k == 'request':      d_request   = v

        d_meta  = d_request['meta']
        if 'askAbout' in d_meta.keys():
            str_askAbout    = d_meta['askAbout']
            if str_askAbout == 'timestamp':
                str_timeStamp   = datetime.datetime.today().strftime('%Y%m%d%H%M%S.%f')
                d_ret['timestamp']              = {}
                d_ret['timestamp']['now']       = str_timeStamp
                b_status                        = True
            if str_askAbout == 'sysinfo':
                d_ret['sysinfo']                = {}
                d_ret['sysinfo']['system']      = platform.system()
                d_ret['sysinfo']['machine']     = platform.machine()
                d_ret['sysinfo']['platform']    = platform.platform()
                d_ret['sysinfo']['uname']       = platform.uname()
                d_ret['sysinfo']['version']     = platform.version()
                d_ret['sysinfo']['memory']      = psutil.virtual_memory()
                d_ret['sysinfo']['cpucount']    = multiprocessing.cpu_count()
                d_ret['sysinfo']['loadavg']     = os.getloadavg()
                d_ret['sysinfo']['cpu_percent'] = psutil.cpu_percent()
                d_ret['sysinfo']['hostname']    = socket.gethostname()
                b_status                        = True
            if str_askAbout == 'echoBack':
                d_ret['echoBack']               = {}
                d_ret['echoBack']['msg']        = d_meta['echoBack']
                b_status                        = True

        return { 'd_ret':   d_ret,
                 'status':  b_status}

    def t_run_process(self, *args, **kwargs):
        """
        Main job handler -- this is in turn a thread spawned from the
        parent listener thread.
        By being threaded, the client http caller gets an immediate
        response without needing to wait on the jobs actually running
        to completion.
        """

        str_cmd             = ""
        d_request           = {}
        d_meta              = {}

        for k,v in kwargs.items():
            if k == 'request': d_request    = v

        d_meta          = d_request['meta']

        if d_meta:
            self.jid    = d_meta['jid']
            self.auid   = d_meta['auid']
            str_cmd     = d_meta['cmd']

        if isinstance(self.jid, int):
            self.jid    = str(self.jid)

        self.dp.qprint("spawing and starting poller thread")

        # Start the 'poller' worker
        self.poller  = Poller(cmd           = str_cmd,
                              debugToFile   = self.b_debugToFile,
                              debugFile     = self.str_debugFile)
        self.poller.start()

        str_timeStamp       = datetime.datetime.today().strftime('%Y%m%d%H%M%S.%f')
        str_uuid            = uuid.uuid4()
        str_dir             = '%s_%s' % (str_timeStamp, str_uuid)
        self.str_jobRootDir = str_dir

        b_jobsAllDone       = False

        p                   = self._ptree

        p.cd('/')
        p.mkcd(str_dir)
        p.touch('d_meta',       json.dumps(d_meta))
        p.touch('cmd',          str_cmd)
        if len(self.auid):
            p.touch('auid',     self.auid)
        if len(self.jid):
            p.touch('jid',      self.jid)

        p.mkdir('start')
        p.mkdir('end')

        jobCount        = 0
        p.touch('jobCount',     jobCount)

        while not b_jobsAllDone:
            try:
                b_jobsAllDone   = self.poller.queueAllDone.get_nowait()
            except queue.Empty:
                self.dp.qprint('Waiting on start job info')
                d_startInfo     = self.poller.queueStart.get()
                str_startDir    = '/%s/start/%d' % (self.str_jobRootDir, jobCount)
                p.mkdir(str_startDir)
                p.cd(str_startDir)
                p.touch('startInfo', d_startInfo.copy())
                p.touch('/%s/startInfo' % str_dir, d_startInfo.copy())

                self.dp.qprint('Waiting on end job info')
                d_endInfo       = self.poller.queueEnd.get()
                str_endDir      = '/%s/end/%d' % (self.str_jobRootDir, jobCount)
                p.mkdir(str_endDir)
                p.cd(str_endDir)
                p.touch('endInfo', d_endInfo.copy())
                p.touch('/%s/endInfo' % str_dir,    d_endInfo.copy())

                p.touch('/%s/jobCount' % str_dir,   jobCount)
                jobCount        += 1
        self.dp.qprint('All jobs processed.')

    def json_filePart_get(self, **kwargs):
        """
        If the requested path is *within* a json "file" on the
        DB, then we need to find the file, and map the relevant
        path to components in that file.
        """

    def DB_get(self, **kwargs):
        """
        Returns part of the DB tree based on path spec in the URL
        """

        r           = C_stree()
        p           = self._ptree

        pcwd        = p.cwd()
        str_URLpath = "/api/v1/"
        for k,v in kwargs.items():
            if k == 'path':     str_URLpath = v

        str_path    = '/' + '/'.join(str_URLpath.split('/')[3:])

        self.dp.qprint("path = %s" % str_path)

        if str_path == '/':
            # If root node, only return list of jobs
            l_rootdir = p.lstr_lsnode(str_path)
            r.mknode(l_rootdir)
        else:
            # Here is a hidden behaviour. If the 'root' dir starts
            # with an underscore, then replace that component of
            # the path with the actual name in list order.
            # This is simply a short hand way to access indexed
            # offsets.

            l_path  = str_path.split('/')
            jobID   = l_path[1]
            # Does the jobID start with an underscore?
            if jobID[0] == '_':
                jobOffset   = jobID[1:]
                l_rootdir   = list(p.lstr_lsnode('/'))
                self.dp.qprint('jobOffset = %s' % jobOffset)
                self.dp.qprint(l_rootdir)
                try:
                    actualJob   = l_rootdir[int(jobOffset)]
                except:
                    return False
                l_path[1]   = actualJob
                str_path    = '/'.join(l_path)

            r.mkdir(str_path)
            r.cd(str_path)
            r.cd('../')
            # if not r.graft(p, str_path):
            # pudb.set_trace()
            if not p.copy(startPath = str_path, destination = r)['status']:
                # We are probably trying to access a file...
                # First, remove the erroneous path in the return DB
                r.rm(str_path)

                # Now, we need to find the "file", parse the json layer
                # and save...
                n                   = 0
                contents            = p.cat(str_path)
                str_pathFile        = str_path
                l_path              = str_path.split('/')
                totalPathLen        = len(l_path)
                l_pathFile          = []
                while not contents and -1*n < totalPathLen:
                    n               -= 1
                    str_pathFile    = '/'.join(str_path.split('/')[0:n])
                    contents        = p.cat(str_pathFile)
                    l_pathFile.append(l_path[n])

                if contents and n<0:
                    l_pathFile      = l_pathFile[::-1]
                    str_access      = ""
                    for l in l_pathFile:
                        str_access += "['%s']" % l
                    self.dp.qprint('str_access = %s' % str_access)
                    try:
                        contents        = eval('contents%s' % str_access)
                    except:
                        contents        = False

                r.touch(str_path, contents)

        p.cd(pcwd)

        self.dp.qprint(r)
        self.dp.qprint(dict(r.snode_root))
        return dict(r.snode_root)

        # return r

    def process(self, request, **kwargs):
        """ Process the message from remote client

        In some philosophical respects, this process() method in fact implements
        REST-like API of its own.

        """

        if len(request):

            REST_header     = ""
            REST_verb       = ""
            str_path        = ""
            json_payload    = ""

            self.dp.qprint("Listener ID - %s: process() - handling request" % (self.worker_id))

            now             = datetime.datetime.today()
            str_timeStamp   = now.strftime('%Y-%m-%d %H:%M:%S.%f')
            self.dp.qprint(Colors.YELLOW)
            self.dp.qprint("***********************************************")
            self.dp.qprint("***********************************************")
            self.dp.qprint("%s incoming data stream" % (str_timeStamp) )
            self.dp.qprint("***********************************************")
            self.dp.qprint("len = %d" % len(request))
            self.dp.qprint("***********************************************")
            self.dp.qprint(Colors.CYAN + "%s\n" % (request.decode()) + Colors.YELLOW)
            self.dp.qprint("***********************************************" + Colors.NO_COLOUR)
            l_raw           = request.decode().split('\n')
            FORMtype        = l_raw[0].split('/')[0]

            self.dp.qprint('Request = ...')
            self.dp.qprint(l_raw)
            REST_header             = l_raw[0]
            REST_verb               = REST_header.split()[0]
            str_path                = REST_header.split()[1]
            json_payload            = l_raw[-1]

            # remove trailing '/' if any on path
            if str_path[-1]         == '/': str_path = str_path[0:-1]

            d_ret                   = {}
            d_ret['status']         = False
            d_ret['RESTheader']     = REST_header
            d_ret['RESTverb']       = REST_verb
            d_ret['action']         = ""
            d_ret['path']           = str_path
            d_ret['receivedByServer'] = l_raw

            if REST_verb == 'GET':
                d_ret['GET']    = self.DB_get(path = str_path)
                d_ret['status'] = True

            self.dp.qprint('json_payload = %s' % json_payload)
            d_ret['client_json_payload']    = json_payload
            d_ret['client_json_len']        = len(json_payload)
            if len(json_payload):
                d_payload           = json.loads(json_payload)
                d_request           = d_payload['payload']
                payload_verb        = d_request['action']
                if 'meta' in d_request.keys():
                    d_meta          = d_request['meta']
                d_ret['payloadsize']= len(json_payload)

                if payload_verb == 'quit':
                    self.dp.qprint('Shutting down server...')
                    d_ret['status'] = True

                if payload_verb == 'run' and REST_verb == 'PUT':
                    d_ret['action']     = payload_verb
                    self.processPUT(                            request     = d_request)
                    d_ret['status'] = True

                if REST_verb == 'POST':
                    self.processPOST(   request = d_request,
                                        ret     = d_ret)
            return d_ret
        else:
            return False

    def processPOST(self, **kwargs):
        """
         Dispatcher for POST
        """

        for k,v in kwargs.items():
            if k == 'request':  d_request   = v
            if k == 'ret':      d_ret       = v

        payload_verb        = d_request['action']
        if 'meta' in d_request.keys():
            d_meta          = d_request['meta']

        d_ret['action'] = payload_verb
        d_ret['meta']   = d_meta

        b_threaded      = False
        if 'threaded' in d_meta.keys():
            b_threaded  = d_meta['threaded']

        if b_threaded:
            self.dp.qprint("Will process request in new thread.")
            method      = None
            str_method  = 't_%s_process' % payload_verb
            try:
                method  = getattr(self, str_method)
            except AttributeError:
                raise NotImplementedError("Class `{}` does not implement `{}`".format(my_cls.__class__.__name__, method_name))

            t_process           = threading.Thread(     target      = method,
                                                        args        = (),
                                                        kwargs      = kwargs)
            t_process.start()
            time.sleep(0.1)
            if payload_verb == 'run':
                d_ret['jobRootDir'] = self.str_jobRootDir
            d_ret['status']     = True
        else:
            self.dp.qprint("Will process request in current thread.")
            d_done              = eval("self.t_%s_process(request = d_request)" % payload_verb)
            try:
                d_ret['d_ret']      = d_done["d_ret"]
                d_ret['status']     = d_done["status"]
            except:
                self.dp.qprint("An error occurred in reading ret structure. Should this method have been threaded?")

        return d_ret

    def processPUT(self, **kwargs):
        """
         Dispatcher for PUT
        """

        d_request       = {}
        str_action      = "run"
        str_cmd         = "save"
        str_DBpath      = self.str_DBpath
        str_fileio      = "json"
        tree_DB         = self._ptree

        for k,v in kwargs.items():
            if k == 'request':  d_request   = v

        str_action      = d_request['action']
        self.dp.qprint('action = %s' % str_action)
        d_meta              = d_request['meta']
        self.dp.qprint('action = %s' % str_action)

        # Optional search criteria
        if 'key'        in d_meta:
            d_search    = self.t_search_process(request = d_request)['d_ret']

            p           = self._ptree
            Tj          = C_stree()
            Tdb         = C_stree()
            for j in d_search.keys():
                d_j = d_search[j]
                for job in d_j.keys():
                    str_pathJob         = '/api/v1/' + job

                    d_job               = self.DB_get(path = str_pathJob)
                    Tj.initFromDict(d_job)
                    Tj.copy(startPath = '/', destination = Tdb)

                    # Tdb.graft(Tj, '/')

                    # self.DB_get(path = str_pathJob).copy(startPath = '/', destination = Tdb)


            # print(Tdb)
            tree_DB     = Tdb


        if 'context'    in d_meta:  str_context     = d_meta['context']
        if 'operation'  in d_meta:  str_cmd         = d_meta['operation']
        if 'dbpath'     in d_meta:  str_DBpath      = d_meta['dbpath']
        if 'fileio'     in d_meta:  str_type        = d_meta['fileio']

        if str_action.lower() == 'run' and str_context.lower() == 'db':
            self.within.DB_fileIO(  cmd         = str_cmd,
                                    fileio      = str_fileio,
                                    dbpath      = str_DBpath,
                                    db          = tree_DB)

class Poller(threading.Thread):
    """
    The Poller checks for running processes based on the internal
    DB and system process table. Jobs that are no longer running are
    removed from the internal DB.
    """

    def __init__(self, **kwargs):

        self.pollTime           = 10
        self.str_cmd            = ""
        self.crunner            = None
        self.queueStart         = queue.Queue()
        self.queueEnd           = queue.Queue()
        self.queueAllDone       = queue.Queue()

        # self.dp.qprint('starting...', level=-1)

        # Debug parameters
        self.str_debugFile      = '/dev/null'
        self.b_debugToFile      = True

        for key,val in kwargs.items():
            if key == 'pollTime':       self.pollTime       = val
            if key == 'cmd':            self.str_cmd        = val
            if key == 'debugFile':      self.str_debugFile  = val
            if key == 'debugToFile':    self.b_debugToFile  = val

        self.dp                 = debug(verbosity   = 0,
                                        level       = -1,
                                        debugFile   = self.str_debugFile,
                                        debugToFile = self.b_debugToFile)

        threading.Thread.__init__(self)


    def run(self):

        timeout = 1
        loop    = 10

        """ Main execution. """

        # Spawn the crunner object container
        self.crunner  = Crunner(cmd         = self.str_cmd,
                                debugToFile = self.b_debugToFile,
                                debugFile   = self.str_debugFile)
        self.crunner.start()

        b_jobsAllDone   = False

        while not b_jobsAllDone:
            try:
                b_jobsAllDone = self.crunner.queueAllDone.get_nowait()
            except queue.Empty:
                # We basically propagate the queue contents "up" the chain.
                self.dp.qprint('Waiting on start job info')
                self.queueStart.put(self.crunner.queueStart.get())

                self.dp.qprint('Waiting on end job info')
                self.queueEnd.put(self.crunner.queueEnd.get())

        self.queueAllDone.put(b_jobsAllDone)
        self.dp.qprint("done with Poller.run")

class Crunner(threading.Thread):
    """
    The wrapper thread about the actual process.
    """

    def __init__(self, **kwargs):
        self.__name             = "Crunner"


        self.queueStart         = queue.Queue()
        self.queueEnd           = queue.Queue()
        self.queueAllDone       = queue.Queue()

        self.str_cmd            = ""

        # Debug parameters
        self.str_debugFile      = '/dev/null'
        self.b_debugToFile      = True

        for k,v in kwargs.items():
            if k == 'cmd':          self.str_cmd        = v
            if k == 'debugFile':    self.str_debugFile  = v
            if k == 'debugToFile':  self.b_debugToFile  = v

        self.shell              = crunner(  verbosity   = 0,
                                            level       = -1,
                                            debugToFile = self.b_debugToFile,
                                            debugFile   = self.str_debugFile)

        self.dp                 = debug(    verbosity   = 0,
                                            level       = -1,
                                            debugFile   = self.str_debugFile,
                                            debugToFile = self.b_debugToFile)
        self.dp.qprint('starting crunner...')

        threading.Thread.__init__(self)

    def jsonJobInfo_queuePut(self, **kwargs):
        """
        Get and return the job dictionary as a json string.
        """

        str_queue   = 'startQueue'
        for k,v in kwargs.items():
            if k == 'queue':    str_queue   = v

        if str_queue == 'startQueue':   queue   = self.queueStart
        if str_queue == 'endQueue':     queue   = self.queueEnd

        # self.dp.qprint(self.shell.d_job)

        queue.put(self.shell.d_job.copy())

    def run(self):

        timeout = 1
        loop    = 10

        """ Main execution. """
        self.dp.qprint("running...")
        self.shell(self.str_cmd)
        # self.shell.jobs_loopctl(    onJobStart  = 'self.jsonJobInfo_queuePut(queue="startQueue")',
        #                             onJobDone   = 'self.jsonJobInfo_queuePut(queue="endQueue")')
        self.shell.jobs_loopctl(    onJobStart  = partial(self.jsonJobInfo_queuePut, queue="startQueue"),
                                    onJobDone   = partial(self.jsonJobInfo_queuePut, queue="endQueue"))
        self.queueAllDone.put(True)
        self.queueStart.put({'allJobsStarted': True})
        self.queueEnd.put({'allJobsDone': True})
        # self.shell.exitOnDone()
        self.dp.qprint('Crunner.run() returning...')
