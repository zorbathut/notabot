#! /cygdrive/c/Python24/python.exe
#
# CalcMe
#
# Ben Wilhelm (zorba@pavlovian.net)

import string
from ircbot import SingleServerIRCBot
from irclib import nm_to_n, nm_to_h, irc_lower, ip_numstr_to_quad, ip_quad_to_numstr
import MySQLdb

def initDb():
    global db
    db = MySQLdb.connect(host='maximillian',user='calcme',passwd='bigblackhardcaulk',db="calcme")
    print db

def getEntry(entry):
    global db
    c=db.cursor()
    print entry
    print len(entry)
    print 'SELECT value FROM current WHERE name = "%s"' % (entry,)
    if c.execute('SELECT value FROM current WHERE name = %s', (entry,)) == 0:
        print "evil"
        return ""
    print "porn"
    return c.fetchone()[0]
    
def getCount(entry):
    global db
    c=db.cursor()
    if c.execute('SELECT count FROM current WHERE name = %s', (entry,)) == 0:
        return ""
    return c.fetchone()[0]

def incrementCount(entry):
    global db
    print "Incrementing " + entry
    c=db.cursor()
    if c.execute('UPDATE current SET count = count+ 1 WHERE name = %s', (entry,)) == 0:
        raise Error, "Can't seem to increment for some reason."
        
def changeEntry(entry, data, user):
    global db
    c=db.cursor()
    if c.execute('SELECT max( version ) FROM versions WHERE name = %s', (entry,)) == 0:
        raise Error, "Select is fucked."
    nextversion = c.fetchone()[0]
    if nextversion == None:
        nextversion = 0
        if c.execute('INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, "", 0)) == 0:
            raise Error, "Insert is fucked."
    else:
        nextversion = nextversion + 1
    print nextversion
    if c.execute('INSERT INTO versions ( name, version, modifier, value ) VALUES ( %s, %s, %s, %s )', (entry, nextversion, user, data)) == 0:
        raise Error, "Versioning is fucked."
    if c.execute('UPDATE current SET value = %s WHERE name = %s', (data, entry)) == 0:
        raise Error, "Updating is fucked."
        
def apropos(data, name, value):
    global db
    c=db.cursor()
    if name == 0 and value == 1:
        if c.execute('SELECT name FROM current WHERE value LIKE CONCAT("%%", %s, "%%")', (data,)) == 0:
            print "Dropped value"
            return "";
    elif name == 1 and value == 0:
        if c.execute('SELECT name FROM current WHERE name LIKE CONCAT("%%", %s, "%%")', (data,)) == 0:
            print "Dropped name"
            return "";
    elif name == 1 and value == 1:
        if c.execute('SELECT name FROM current WHERE name LIKE CONCAT("%%", %s, "%%") OR value LIKE CONCAT("%%", %s, "%%")', (data,data)) == 0:
            print 'SELECT name FROM current WHERE name LIKE CONCAT("%%", %s, "%%") OR value LIKE CONCAT("%%", %s, "%%")' % (data,data)
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
        self.channel = channel

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        c.join(self.channel)

    def on_privmsg(self, c, e):
        self.do_command(e)

    def on_pubmsg(self, c, e):
		self.do_command(e)

    def do_command(self, e):
        print e.eventtype()
        print e.source()
        print e.target()
        print e.arguments()
        instr = e.arguments()[0].split(' ', 1)
        cmd = instr[0]
        if len(instr) > 1:
            instr[1] = instr[1].strip()
        
        nick = nm_to_n(e.source())
        c = self.connection
       
        """planned variables: cmd, source, target, entry, data"""
        
        if cmd == "calc" or cmd == "status" or cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc" or cmd == "apropos" or cmd == "aproposk" or cmd == "aproposv":
            if e.eventtype() == "pubmsg":
                target = e.target()
                source = e.target()
            else:
                target = nick
                source = nick
        elif cmd == "tell":
            if len(instr) == 1 or instr[1] == "":
                return
            tellparse = instr[1].split(' ', 2)
            if len(tellparse) == 3:
                tellparse[0] = tellparse[0].strip()
                tellparse[2] = tellparse[2].strip()
            if tellparse[2] == "":
                return
            target = tellparse[0]
            source = nick
            entry = tellparse[2]
        else:
            return

        if cmd == "calc" or cmd == "status" or cmd == "rmcalc" or cmd == "apropos" or cmd == "aproposk" or cmd == "aproposv":
            if len(instr) == 1 or instr[1] == "":
                return
            else:
                entry = instr[1]
            data = ""
        elif cmd == "tell":
            pass
        elif cmd == "mkcalc" or cmd == "chcalc":
            if len(instr) == 1 or instr[1] == "":
                return
            dat = instr[1].split('=', 1)
            if len(dat) != 2:
                return
            dat[0] = dat[0].strip()
            dat[1] = dat[1].strip()
            entry = dat[0]
            data = dat[1]
        else:
            raise Error, "Shouldn't get here."
            
        entry = entry.lower()
            
        if (cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc") and nick not in self.channels.items()[0][1].opers():
            c.notice(nick, "Sorry, you don't have permission to do that. Op yourself or stop trying.")
            return
            
        if cmd == "tell" and nick not in self.channels.items()[0][1].opers() and nick not in self.channels.items()[0][1].voiced():
            c.notice(nick, "Sorry, you don't have permission to do that. Op/voice yourself or stop trying.")
            return
            
        if target[0] == '#' and nick not in self.channels.items()[0][1].opers() and nick not in self.channels.items()[0][1].voiced():
            c.notice(nick, "Sorry, you don't have permission to do that publicly. Op/voice yourself or send me a message.")
            return
            
        if cmd == "calc" or cmd == "tell":
            data = getEntry(entry)
            if data == "":
                c.privmsg(source, "no entry for " + entry)
            else:
                if cmd == "tell":
                    c.privmsg(target, nick + " wanted me to tell you:")
                    c.privmsg(source, 'sent calc for "%s" to %s' % (entry, target))
                c.privmsg(target, entry + " = " + data)
                incrementCount(entry)
        elif cmd == "status":
            data = getCount(entry)
            if data == "":
                c.privmsg(source, "no entry for " + entry)
            else:
                c.privmsg(target, '"%s" has been queried %d times.' % (entry, data))
        elif cmd == "mkcalc" or cmd == "rmcalc" or cmd == "chcalc":
            olddata = getEntry(entry)
            if cmd == "rmcalc" and olddata == "":
                c.privmsg(source, '"%s" is not a valid calc' % (entry,))
                return
            if cmd == "mkcalc" and olddata != "":
                c.privmsg(source, 'I already have an entry for "%s"' % (entry,))
                return
            changeEntry(entry, data, e.source())
            c.privmsg(target, "Change complete.")
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
            c.privmsg(target, output)
        else:
            raise Error, "Shouldn't get here."


def main():
    import sys
    print len(sys.argv)
    if len(sys.argv) != 4:
        print "Usage: testbot <server[:port]> <channel> <nickname>"
        sys.exit(1)
        
    initDb()

    s = string.split(sys.argv[1], ":", 1)
    server = s[0]
    if len(s) == 2:
        try:
            port = int(s[1])
        except ValueError:
            print "Error: Erroneous port."
            sys.exit(1)
    else:
        port = 6667
    channel = sys.argv[2]
    nickname = sys.argv[3]

    bot = TestBot(channel, nickname, server, port)
    bot.start()

if __name__ == "__main__":
    main()
