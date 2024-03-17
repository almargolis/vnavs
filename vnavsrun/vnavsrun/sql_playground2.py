import os
import random
import sqlite3
import sys
import time

field_defs = (
    ["LONGITUDE", "REAL", "-121.0 - random.random()"],
    ["HEADING", "REAL", "360 * random.random()"],
    ["LATITUDE", "REAL", "37.0 + random.random()"],
)

if len(sys.argv) < 3:
    print("Usage: python %s <fld ct> <record ct>" % sys.argv[0])
    sys.exit(1)

field_ct_parm = int(sys.argv[1])
test_ct_parm = int(sys.argv[2])
assert (field_ct_parm > 0) and (field_ct_parm <= len(field_defs))

db_file_name = "test.db"
os.remove(db_file_name)
db = sqlite3.connect(db_file_name)
cursor = db.cursor()

sql_field_list = []
for ix in range(field_ct_parm):
    sql_field_list.append(field_defs[ix][0] + " " + field_defs[ix][1])

cursor.execute("CREATE TABLE MissionLog ({})".format(", ".join(sql_field_list)))

start_time = time.time()
random.seed()
for x in xrange(test_ct_parm):
    fld_values = []
    for fld_ix in xrange(field_ct_parm):
        fld_values.append(eval(field_defs[fld_ix][2]))
    cursor.execute("INSERT INTO MissionLog VALUES (?, ?);", fld_values)
elapsed_time = time.time() - start_time
print(
    "Inserted %d records in %8.3f seconds. %6.1f records/second."
    % (test_ct_parm, elapsed_time, test_ct_parm / elapsed_time)
)
