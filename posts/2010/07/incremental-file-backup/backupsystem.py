from optparse import OptionParser
import hashlib
import sys, os, shutil

parser = OptionParser()
			  
## Options
#parser.add_option("-h", "--help", action="help")

parser.add_option("--rootfolder", action="store", dest="rootfolder", help="The directory to mirror from")
parser.add_option("--backupfolder", action="store", dest="backupfolder", help="The directory to mirror to")
parser.add_option("--datafolder", action="store", dest="datafolder", help="The directory that stores the HASH-named files")
parser.add_option("--datalevels", action="store", type="int", dest="datalevels", default=0, help="Subfolder levels in DATAFOLDER. Default: 0")
parser.add_option("--createdirs", action="store_true", dest="createdirs", default=False, help="Assumes yes to all dir-creation questions")
parser.add_option("--pauseonerror", action="store_true", dest="pauseonerror", default=False, help="Pause when errors occur?")
parser.add_option("--awaituserinput", action="store_true", dest="awaituserinput", default=False, help="Waits for user to press [ENTER] before backing up")
parser.add_option("--folderspause", action="store_true", dest="folderspause", default=False, help="Waits for user to press [ENTER] before doing anything with folders")
parser.add_option("--filespause", action="store_true", dest="filespause", default=False, help="Waits for user to press [ENTER] before doing anything with files")
parser.add_option("--dostats", action="store_true", dest="dostats", default=False, help="Displays some statistics at the end of the job, requires 1 verbose")
parser.add_option("--doprogress", action="store", dest="doprogress", default=0, type="int", metavar="N", help="Displays some statistics while running, requires 1 verbose. Progress will be displayed ever N files.")
parser.add_option("--ignorefileexists", action="store_true", dest="ignorefileexists", default=False, help="Ignores errors stating a file / folder exists")

validhashmethods = ['MD5', 'SHA1', 'SHA224', 'SHA256', 'SHA512']
parser.add_option("--hash", action="store", dest="hashmethod", type="choice", choices=validhashmethods, help="The hash method to use.")

parser.add_option("-v", action="count", dest="verbose", default=0, help="Verbosity. 3 levels, add more for greater effect.")

(options, args) = parser.parse_args()

if options.rootfolder == None:
	print "Error: rootfolder is required."
	sys.exit(0)
	
if options.backupfolder == None:
	print "Error: backupfolder is required."
	sys.exit(0)
	
if options.datafolder == None:
	print "Error: datafolder is required."
	sys.exit(0)

## Helper functions
## HASH HELPER FUNCTIONS
def hashfile(filename, method):
	hashmethod = hashlib.new(method)

	f = open(filename)
	while True:
		p = f.read(8192)
		if not p:
			break
		hashmethod.update(p)
	
	return hashmethod.hexdigest().upper()

## PATH HELPER FUNCTIONS
def pathsplit(p, rest=[]):
    (h,t) = os.path.split(p)
    if len(h) < 1: return [t]+rest
    if len(t) < 1: return [h]+rest
    return pathsplit(h,[t]+rest)

def commonpath(l1, l2, common=[]):
    if len(l1) < 1: return (common, l1, l2)
    if len(l2) < 1: return (common, l1, l2)
    if l1[0] != l2[0]: return (common, l1, l2)
    return commonpath(l1[1:], l2[1:], common+[l1[0]])

def relpath(p1, p2):
    (common,l1,l2) = commonpath(pathsplit(p1), pathsplit(p2))
    p = []
    if len(l1) > 0:
        p = [ '../' * len(l1) ]
    p = p + l2
    return os.path.join( *p )

## DEBUG HELPER FUNCTION
def printdebug(message, level=1):
	if options.verbose >= level:
		if level == 0:
			print "[MESSAGE]", message
		elif level == 1:
			print "[MESSAGE]", message
		elif level == 2:
			print "[INFO]", message
		elif level >= 3:
			print "[DEBUG]", message

# Check input
Valid = ""
printdebug("Checking Inputs", 1)

if os.path.exists(options.rootfolder):
	# Valid
	printdebug("ROOTFOLDER exists", 3)
else:
	# Invalid
	Valid = "Root folder does not exist"
	
	printdebug("ROOTFOLDER does not exist")
	
if os.path.exists(options.backupfolder):
	# Valid
	printdebug("BACKUPFOLDER exists", 3)
else:
	# Invalid
	printdebug("BACKUPFOLDER does not exist", 2)
		
	if options.createdirs:
		# Create directory
		os.makedirs(options.backupfolder)
		
		printdebug("Created BACKUPFOLDER", 2)
	else:
		# Get user input
		while True:
			result = raw_input("Backupfolder does not exist. Create? (Y/N)").upper()
			
			printdebug("User input: " + str(result), 3)
				
			if result == "N":
				Valid = "Backup folder does not exist"
				break
			elif result == "Y":
				os.makedirs(options.backupfolder)
				
				printdebug("Created BACKUPFOLDER", 2)
					
				break

if os.path.exists(options.datafolder):
	# Valid
	printdebug("DATAFOLDER exists", 3)
else:
	# Invalid
	printdebug("DATAFOLDER does not exist", 2)
		
	if options.createdirs:
		# Create directory
		os.makedirs(options.datafolder)
		
		printdebug("Created DATAFOLDER", 2)
	else:
		# Get user input
		while True:
			result = raw_input("Datafolder does not exist. Create? (Y/N)").upper()
			
			printdebug("User input: " + str(result), 3)
				
			if result == "N":
				Valid = "Data folder does not exist"
				break
			elif result == "Y":
				os.makedirs(options.datafolder)
				
				printdebug("Created DATAFOLDER", 2)
					
				break

printdebug("  rootfolder: " + options.rootfolder, 1)
printdebug("  backupfolder: " + options.backupfolder, 1)
printdebug("  datafolder: " + options.datafolder, 1)
printdebug("  datalevels: " + str(options.datalevels), 1)
printdebug("  createdirs: " + str(options.createdirs), 1)
printdebug("  pauseonerror: " + str(options.pauseonerror), 1)
printdebug("  awaituserinput: " + str(options.awaituserinput), 1)
printdebug("  folderspause: " + str(options.folderspause), 1)
printdebug("  filespause: " + str(options.filespause), 1)
printdebug("  dostats: " + str(options.dostats), 1)
printdebug("  doprogress: " + str(options.doprogress), 1)
printdebug("  ignorefileexists: " + str(options.ignorefileexists), 1)
printdebug("  hash: " + str(options.hashmethod), 1)
printdebug("  verbose: " + str(options.verbose), 1)

printdebug("Done Checking Inputs", 1)
	
if Valid != "":
	print "Error occured in input."
	print "Message:", Valid
	
	# Exit
	sys.exit(0)

## Await user input
if options.awaituserinput:
	# Wait
	raw_input("Waiting user input. Press [ENTER] to continue.")

## Code
stats = {"files_total": 0, "files_new": 0, "files_old": 0, "directories_total": 0}

printdebug("Begun work", 1)

for root, dirs, files in os.walk(options.rootfolder):
	if (options.verbose >= 3):
		printdebug("New directory (F: " + str(len(files)) + " D: " + str(len(dirs)) + ") - " + root, 3)
	else:
		printdebug("New directory - " + root, 2)
	
	# Make dirs
	if len(dirs) > 0:
		printdebug("Making subdirs", 3)
	
	for dir in dirs:
		# Make dir
		copydir = os.path.join(root, dir)					# Old dir
		printdebug("copydir (old dir):   " + copydir, 3)
		
		backupdir = os.path.join(options.backupfolder, copydir.replace(relpath(copydir, options.rootfolder) + "/", ""))		# New dir
		printdebug("backupdir (new dir): " + backupdir, 3)
		
		if options.folderspause:
			# Wait for input
			raw_input("Waiting user input before making a new backup dir. Press [ENTER] to continue.")
		
		#print "Making dir:", copydir
		#print "New    dir:", backupdir
		#raw_input()
		
		try:
			os.mkdir(backupdir)
			
			stats['directories_total'] += 1					# Stats
		except Exception as ex:
			if not ((ex.errno == 2 or ex.errno == 17) and options.ignorefileexists):		# Check for ignoring file exists
				## Error: 2; Message: No such file or directory
				## Error: 17; Message: File exists
				# Don't ignore
				printdebug("ERROR: Failed to make subfolder (" + backupdir + "). Error: (" + str(ex.errno) + ") " + ex.strerror, 1)
	
	# Make files
	if len(files) > 0:
		printdebug("Making files", 3)
	
	for file in files:
		# Hash
		copyfile = os.path.join(root, file)					# Old file - the one we'll backup
		printdebug("Beginning file: " + copyfile, 2)
		
		mhash = ""
		try:
			# Hash file
			mhash = hashfile(copyfile, options.hashmethod)
			printdebug("Hashed file:     " + mhash, 3)
		except Exception as ex:
			# Don't ignore
			printdebug("ERROR: Failed to make hash (" + copyfile + ", " + options.hashmethod + "). Error: (" + str(ex.errno) + ") " + ex.strerror, 1)
		
		if mhash != "":
			if options.datalevels == 0:																							# Data file
				datafile = os.path.join(options.datafolder, mhash)
			else:
				# Split the hash
				path = ""
				for i in range(0, options.datalevels):
					# Take two characters out of the hash
					# Add as a dir
					path += mhash[:2] + "/"
					
					# Remove two characters from hash
					mhash = mhash[2:]
				
				datadir = os.path.join(options.datafolder, path)
				# Make the directory
				if os.path.exists(datadir):
					printdebug("Data dir exists: " + datadir, 3)
				else:
					printdebug("Making data dir: " + datadir, 3)
					os.makedirs(datadir)
				
				# Add remaining hash
				path += mhash
				datafile = os.path.join(options.datafolder, path)
			
			backupfile = os.path.join(options.backupfolder, copyfile.replace(relpath(copyfile, options.rootfolder) + "/", ""))	# New backup
			
			printdebug("File data dir:   " + datafile, 3)
			printdebug("File backup dir: " + backupfile, 3)
			
			if options.filespause:
				# Wait for input
				raw_input("Waiting user input before making a new data file. Press [ENTER] to continue.")
				
			try:
				# Check if datafile exists
				if os.path.exists(datafile):
					# Make hardlink to datafile
					printdebug("Datafile:        Exists", 3)
					stats['files_old'] += 1					# Stats
				else:
					# Copy copyfile into datafile
					printdebug("Datafile:        Copying", 3)
					
					shutil.copy(copyfile, datafile)
					stats['files_new'] += 1					# Stats
					
					printdebug("Datafile:        Copied", 3)
			except Exception as ex:
				if not (ex.errno == 17 and options.ignorefileexists):		# Check for ignoring file exists
					## Error: 17; Message: File exists
					# Don't ignore
					printdebug("ERROR: Failed to make datafi…