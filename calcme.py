#! /cygdrive/c/Python24/python.exe
#
# CalcMe
#
# Ben Wilhelm (zorba@pavlovian.net)

import string
from ircbot import SingleServerIRCBot
from irclib import nm_to_n, nm_to_h, irc_lower, ip_numstr_to_quad, ip_quad_to_numstr
import MySQLdb
import time as time
import sys as sys

def itime():
    return int(time.time())

def initDb():
    global db
    db = MySQLdb.connect(host='maximillian',user='calcme',passwd='bigblackhardcaulk',db="calcme")
    print db

def safeExecute(cursor, string, params):
    try:
        rv=cursor.execute(string, params)
        return cursor, rv
    except MySQLdb.OperationalError:
        print "Fuck, caught OperationalError"
        initDb()
        cursor=db.cursor()
        rv=cursor.execute(string, params)
        return cursor, rv

def getPermissionDict():
    levels = {-1:'IGNORE', 0:'USER', 1:'PUBLIC', 2:'CHANGE', 3:'AUTHORIZE', 4:'GOD'}
    print [(value, key) for key, value in levels.iteritems()]
    revlevels = dict([(value, key) for key, value in levels.iteritems()])
    return levels, revlevels

def greaterPermission(lhs, rhs):
    levels, revlevels = getPermissionDict()
    lhsl = revlevels[lhs]
    rhsl = revlevels[rhs]
    return levels[max(lhsl, rhsl)]
    
def adequatePermission(needed, have):
    levels, revlevels = getPermissionDict()
    print "got", have, "needed", needed, "result", revlevels[needed] <= revlevels[have]
    return revlevels[needed] <= revlevels[have]

def getPermissions(user, nick, channel):
    global db
    c=db.cursor()
    c, rv = safeExecute(c, 'SELECT max(permlev) FROM perms WHERE %s LIKE hostmask', (user,))
    cp = c.fetchone()[0]
    if cp == None:
        cp = "USER"
    print "permoutput:", cp
    if channel.is_oper(nick):
        cp = greaterPermission(cp, 'AUTHORIZE')
    return cp

def getEntry(entry):
    global db
    c=db.cursor()
    c, rv = safeExecute(c, 'SELECT value FROM current WHERE name = %s', (entry,))
    if rv == 0:
        return ""
    return c.fetchone()[0]
    
def getCount(entry):
    global db
    c=db.cursor()
    c, rv = safeExecute(c, 'SELECT count FROM current WHERE name = %s', (entry,))
    if rv == 0:
        return 0
    return c.fetchone()[0]

def incrementCount(entry):
    global db
    c=db.cursor()
    c, rv = safeExecute(c, 'UPDATE current SET count = count + 1 WHERE name = %s', (entry,))
    if rv == 0:
        c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, "", 1))
        if rv == 0:
            raise Error, "Can't seem to increment for some reason."

def setCount(entry, count):
    global db
    c=db.cursor()
    print count, entry
    c, rv = safeExecute(c, 'UPDATE current SET count = %s WHERE name = %s', (count,entry))
    if rv == 0:
        c, rv = safeExecute(c, 'SELECT * FROM current WHERE count = %s AND name = %s', (count,entry))
        if rv == 0:
            c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, "", count))
            raise Error, "Can't seem to set for some reason."

def changeEntry(entry, data, user):
    global db
    c=db.cursor()
    c, rv = safeExecute(c, 'SELECT max( version ) FROM versions WHERE name = %s', (entry,))
    if rv == 0:
        raise Error, "Select is fucked."
    nextversion = c.fetchone()[0]
    if nextversion == None:
        nextversion = 0
    else:
        nextversion = nextversion + 1
    c, rv = safeExecute(c, 'INSERT INTO versions ( name, version, modifier, value, changed ) VALUES ( %s, %s, %s, %s, NOW() )', (entry, nextversion, user, data))
    if rv == 0:
        raise Error, "Versioning is fucked."
    c, rv = safeExecute(c, 'UPDATE current SET value = %s WHERE name = %s', (data, entry))
    if rv == 0:
        c, rv = safeExecute(c, 'SELECT * FROM current WHERE value = %s AND name = %s', (data,entry))
        if rv == 0:
            c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, data, 0))
            if rv == 0:
                raise Error, "Current is fucked weirdly."


def apropos(data, name, value):
    global db
    c=db.cursor()
    if name == 0 and value == 1:
        c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND value LIKE CONCAT("%%", %s, "%%") ORDER BY name', (data,))
        if rv == 0:
            print "Dropped value"
            return "";
    elif name == 1 and value == 0:
        c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND name LIKE CONCAT("%%", %s, "%%") ORDER BY name', (data,))
        if rv == 0:
            print "Dropped name"
            return "";
    elif name == 1 and value == 1:
        c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND ( name LIKE CONCAT("%%", %s, "%%") OR value LIKE CONCAT("%%", %s, "%%") ) ORDER BY name', (data,data))
        if rv == 0:
            print "Dropped both"
            return "";
    else:
        raise Error, "Apropos is fucked."
    output = [];
    while 1:
        tv = c.fetchone();
        if tv == None:
            break
        output.append(tv[0])
    return output

class TestBot(SingleServerIRCBot):
    def __init__(self, channel, nickname, server, port=6667):
        SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self.channel = channel.split(':')[0]
        if len(channel.split(':')) > 1:
            self.channelkey = channel.split(':')[1]
        else:
            self.channelkey = ""
        self.nextspeak = itime()
        self.lastsaid = []
        self.lasttargeted = {}
        self.curtargets = {}
        self.timerRunning = 0
        
    def updateLastsaid(self):
        print self.lastsaid
        while len(self.lastsaid) and self.lastsaid[0][0] < itime() - 15:
            self.lastsaid = self.lastsaid[1:]
        print self.lastsaid
        
    def queueMessage(self, target, data, cull = False):
        print "queueing ", target, data
        self.updateLastsaid()
        if not self.curtargets.has_key(target):
            self.curtargets[target] = []
        if not self.lasttargeted.has_key(target):
            self.lasttargeted[target] = 0
        for time, value in self.lastsaid:
            if value == (target, data):
                if len(self.curtargets[target]) == 0:
                    del self.curtargets[target]
                return
        #print self.lastsaid
        #print self.curtargets
        #print self.timerRunning
        #print self.lastspoken
        #print itime()
        if not cull or not self.curtargets[target].count(data):
            self.curtargets[target].append(data)
            if not self.timerRunning and self.nextspeak <= itime():
                self.timerRunning = 1
                self.dequeueMessage()
            elif not self.timerRunning:
                self.timerRunning = 1
                self.ircobj.execute_delayed(1, self.dequeueMessage, ())
        elif len(self.curtargets[target]) == 0:
            del self.curtargets[target]
            
    def dequeueMessage(self):
        print "entering deque"
        if self.nextspeak > itime():
            self.ircobj.execute_delayed(1, self.dequeueMessage, ())
            return
        self.updateLastsaid()
        while 1:
            target = ("","")
            besttime = itime() + 60
            for key in self.curtargets.iterkeys():
                if self.lasttargeted[key] < besttime:
                    besttime = self.lasttargeted[key]
                    target = key
            if target == ("",""):
                raise Error, "Queue fucked"
            data = self.curtargets[target][0]
            print "snagorated ", target, data
            print (target, data)
            if len(self.curtargets[target]) == 1:
                del self.curtargets[target]
            else:
                self.curtargets[target] = self.curtargets[target][1:]
            self.lastsaid.append((itime(),(target,data)))
            self.lasttargeted[target] = itime()
            if target[0] == 'notice':
                self.connection.notice(target[1], data)
            elif target[0] == 'privmsg':
                self.connection.privmsg(target[1], data)
            self.nextspeak = max(self.nextspeak + 2, itime() - 6 + 2)
            if len(self.curtargets):
                self.dequeueMessage()
                #self.ircobj.execute_delayed(1, self.dequeueMessage, ())
            else:
                self.timerRunning = 0
            return

            
        """
            if target[0] == 'notice':
            self.connection.notice(target[1], data)
        elif target[0] == 'privmsg':
            self.connection.privmsg(target[1], data)"""
        
        

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        c.join(self.channel, self.channelkey)

    def on_privmsg(self, c, e):
        self.do_command(e)

    def on_pubmsg(self, c, e):
        self.do_command(e)
        
    def on_kick(self, c, e):
        c.join(self.channel, self.channelkey)
        
    def on_disconnect(self, c, e):
        print "Disconnected, sleeping"
        time.sleep(30)
        print "Dying"
        sys.exit(1)
        
    def on_bannedfromchan(self, c, e):
        print "Banned, sleeping"
        time.sleep(30)
        print "Retrying"
        c.join(self.channel, self.channelkey)

    def do_command(self, e):
        #print e.eventtype()
        #print e.source()
        #print e.target()
        #print e.arguments()
        striparg = e.arguments()[0].replace("\x02", "").replace("\x1f", "").replace("\x03", "")
        
        instr = striparg.split(' ', 1)
        cmd = instr[0]
        if len(instr) > 1:
            instr[1] = instr[1].strip()
        
        nick = nm_to_n(e.source())
        c = self.connection
       
        """planned variables: cmd, source, target, entry, data"""
        
        confused = 0
        
        if cmd == "calc" or cmd == "status" or cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc" or cmd == "apropos" or cmd == "aproposk" or cmd == "aproposv" or cmd == "apropos2" or cmd == "help":
            if e.eventtype() == "pubmsg":
                target = e.target()
                source = e.target()
            else:
                target = nick
                source = nick
        elif cmd == "tell":
            if len(instr) == 1 or instr[1] == "":
                confused = 1
                entry = ""
                source = nick
                target = ""
            else :
                tellparse = instr[1].split(' ', 1)
                if len(tellparse) == 2:
                    tellparse[1:] = tellparse[1].strip().split(' ', 1)
                    if len(tellparse) == 3:
                        tellparse[0] = tellparse[0].strip()
                        tellparse[2] = tellparse[2].strip()
                if len(tellparse) != 3 or tellparse[2] == "":
                    confused = 1
                    entry = ""
                    source = nick
                    target = ""
                else:
                    target = tellparse[0]
                    source = nick
                    entry = tellparse[2]
        else:
            return

        if cmd == "calc" or cmd == "status" or cmd == "rmcalc" or cmd == "apropos" or cmd == "aproposk" or cmd == "aproposv" or cmd == "apropos2":
            if len(instr) == 1 or instr[1] == "":
                confused = 1
                entry = ""
            else:
                entry = instr[1]
            data = ""
        elif cmd == "tell":
            pass
        elif cmd == "mkcalc" or cmd == "chcalc":
            if len(instr) == 1 or instr[1] == "":
                confused = 1
                entry = ""
                data = ""
            else:
                dat = instr[1].split('=', 1)
                if len(dat) != 2 or dat[0].strip() == "" or dat[1].strip() == "":
                    confused = 1
                    entry = ""
                    data = ""
                else:
                    dat[0] = dat[0].strip()
                    dat[1] = dat[1].strip()
                    entry = dat[0]
                    data = dat[1]
        elif cmd == "help":
            entry = ""
            data = ""
        else:
            raise Error, "Shouldn't get here."
            
        entry = entry.lower()
        
        print self.channels
        print self.channels[self.channel]
        print self.channels[self.channel].userdict
        print self.channels[self.channel].operdict
        print self.channels[self.channel].voiceddict
        print nick
        print self.channels[self.channel].operdict.has_key(nick)
        print self.channels[self.channel].is_oper(nick)
        
        permlev = getPermissions(e.source(), nick, self.channels[self.channel])
        print permlev
        
        if permlev == 'IGNORE':
            return
            
        if (cmd == "apropos2"):
            self.queueMessage(('notice', nick), "apropos2 no longer exists. Use aproposk to search keys, aproposv to search values, or apropos to search both.")
            return
        
        if (confused):
            self.queueMessage(('notice', nick), "Confused? Type help in msg for a list of available commands.")
            return
        
        if (cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc") and not adequatePermission('CHANGE', permlev):
            self.queueMessage(('notice', nick), "Sorry, you don't have permission to do that. Op yourself or stop trying.")
            return
            
        if cmd == "tell" and not adequatePermission('PUBLIC', permlev):
            self.queueMessage(('notice', nick), "Sorry, you don't have permission to do that. Op/voice yourself or stop trying.")
            return
            
        if target[0] == '#' and not adequatePermission('PUBLIC', permlev):
            self.queueMessage(('notice', nick), "Sorry, you don't have permission to do that publicly. Op/voice yourself or send me a message.")
            return
            
        if cmd == "calc" or cmd == "tell":
            data = getEntry(entry)
            """ this whole section should be a lot better """
            if data == "":
                if cmd == "tell":
                    self.queueMessage(('notice', source), "no entry for " + entry, True)
                else:
                    self.queueMessage(('privmsg', source), "no entry for " + entry, True)
            else:
                if cmd == "tell":
                    self.queueMessage(('privmsg', target), nick + " wanted me to tell you:", True)
                    self.queueMessage(('notice', source), 'sent calc for "%s" to %s' % (entry, target), True)
                self.queueMessage(('privmsg', target), entry + " = " + data, True)
            incrementCount(entry)
        elif cmd == "status":
            data = getCount(entry)
            self.queueMessage(('privmsg', source), '"%s" has been queried %d times.' % (entry, data), True)
        elif cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc":
            olddata = getEntry(entry)
            if cmd == "rmcalc" and olddata == "":
                self.queueMessage(('privmsg', source), '"%s" is not a valid calc' % (entry,), True)
                return
            if cmd == "mkcalc" and olddata != "":
                self.queueMessage(('privmsg', source), 'I already have an entry for "%s"' % (entry,))
                return
            changeEntry(entry, data, e.source())
            self.queueMessage(('privmsg', target), "Change complete.")
        elif cmd == "apropos" or cmd == "aproposv" or cmd == "aproposk":
            if cmd == "apropos":
                ki = 1
                val = 1
            elif cmd == "aproposv":
                ki = 0
                val = 1
            elif cmd == "aproposk":
                ki = 1
                val = 0
            else:
                raise Error, "Fucked!"
            returnval = apropos(entry, ki, val)
            output = "found: "
            if returnval == "":
                output = output + "no matches"
            else:
                for ite in returnval:
                    output = output + ( '"%s" ' % ite )
            self.queueMessage(('privmsg', target), output, True)
        elif cmd == "help":
            if target[0] == '#':
                destination = ('notice', source)
            else:
                destination = ('privmsg', source)
            self.queueMessage(destination, "Help for permission level " + permlev, True)
            if adequatePermission('USER', permlev):
                self.queueMessage(destination, "USER and higher: calc apropos aproposk aproposv status", True)
            if adequatePermission('PUBLIC', permlev):
                self.queueMessage(destination, "PUBLIC and higher: calc tell", True)
            if adequatePermission('CHANGE', permlev):
                self.queueMessage(destination, "CHANGE and higher: mkcalc rmcalc chcalc", True)
            if adequatePermission('AUTHORIZE', permlev):
                self.queueMessage(destination, "AUTHORIZE and higher:", True)
            if adequatePermission('GOD', permlev):
                self.queueMessage(destination, "GOD and higher:", True)
            self.queueMessage(destination, "\"help command\" for detailed help", True)
        else:
            raise Error, "Shouldn't get here."

def crazyfunk():
    return 5, 7

def main():
    import sys
    print len(sys.argv)
    if len(sys.argv) == 1:
        print "Usages: testbot run <server[:port]> <channel> <nickname>"
        print "        testbot load <filename>"
        sys.exit(1)
    if sys.argv[1] == "run":
        if len(sys.argv) != 5:
            print "Usage: testbot <server[:port]> <channel> <nickname>"
            sys.exit(1)
            
        initDb()
    
        s = string.split(sys.argv[2], ":", 1)
        server = s[0]
        if len(s) == 2:
            try:
                port = int(s[1])
            except ValueError:
                print "Error: Erroneous port."
                sys.exit(1)
        else:
            port = 6667
        channel = sys.argv[3]
        nickname = sys.argv[4]
    
        bot = TestBot(channel, nickname, server, port)
        bot.start()
    elif sys.argv[1] == "load":
        if len(sys.argv) != 3:
            print "Missing filename"
        initDb()
        input = open(sys.argv[2])
        for x in input:
            tok = x.split("::", 3)
            print "Adding %s: %s" % (tok[1], tok[3])
            changeEntry(tok[1], tok[3], tok[0])
            setCount(tok[1], int(tok[2]))
    else:
        print "Error"
        sys.exit(1)

if __name__ == "__main__":
    main()
