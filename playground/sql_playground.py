import os
import random
import sqlite3
import sys
import time

db_file_name = "test.db"
os.remove(db_file_name)
db = sqlite3.connect(db_file_name)
cursor = db.cursor()

cursor.execute("CREATE TABLE MissionLog (LONGITUDE, LATITUDE)")

test_count = int(sys.argv[1])
start_time = time.time()
random.seed()
for x in xrange(test_count):
    longitude = -121.0 - random.random()
    latitude = 37.0 + random.random()
    cursor.execute("INSERT INTO MissionLog VALUES (?, ?);", (longitude, latitude))
elapsed_time = time.time() - start_time
print(
    "Inserted %d records in %8.3f seconds. %6.1f records/second."
    % (test_count, elapsed_time, test_count / elapsed_time)
)
