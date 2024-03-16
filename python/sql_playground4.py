import os
import random
import sqlite3
import sys
import time

field_defs = (
			['LONGITUDE', 'REAL', -121.0, '-'],
			['HEADING', 'REAL', 360.0, '*'],
			['LATITUDE', 'REAL', 37.0, '+']
		)

class Test(object):
    __slots__ = ('fld_ct', 'rec_ct', 'db_file_name', 'db', 'cursor', 'insert_query')
    def __init__(self, fld_ct, rec_ct):
        self.fld_ct = fld_ct
        self.rec_ct = rec_ct
        self.db_file_name = 'test.db'
        os.remove(self.db_file_name)
        self.db = sqlite3.connect(self.db_file_name)
        self.cursor = self.db.cursor()

        sql_field_list = []
        insert_parms = []
        for ix in range(self.fld_ct):
            sql_field_list.append(field_defs[ix][0] + " " + field_defs[ix][1])
            insert_parms.append('?')
        self.insert_query = "INSERT INTO MissionLog VALUES (%s);" % ", ".join(insert_parms)

        self.cursor.execute("CREATE TABLE MissionLog ({})".format(", ".join(sql_field_list)))

    def RunTest(self):
        start_time = time.time()
        random.seed()
        for x in xrange(self.rec_ct):
            fld_values = []
            for fld_ix in xrange(self.fld_ct):
                this_def = field_defs[fld_ix]
                this_val = this_def[2]
                """
                if this_def[3] == '+':
                    this_val += random.random()
                elif this_def[3] == '-':
                    this_val -= random.random()
                elif this_def[3] == '*':
                    this_val *= random.random()
                """
                this_op = this_def[3]
                if this_op == '+':
                    this_val += random.random()
                elif this_op == '-':
                    this_val -= random.random()
                elif this_op == '*':
                    this_val *= random.random()
                fld_values.append(this_val)
            #print(fld_values)
            self.cursor.execute(self.insert_query, fld_values)
        elapsed_time = time.time() - start_time
        print("Inserted %d records in %8.3f seconds. %6.1f records/second." % (self.rec_ct, elapsed_time, self.rec_ct/ elapsed_time))

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python %s <fld ct> <record ct>" % sys.argv[0])
        sys.exit(1)

    field_ct_parm = int(sys.argv[1])
    test_ct_parm = int(sys.argv[2])
    assert (field_ct_parm > 0) and (field_ct_parm <= len(field_defs))
    t = Test(field_ct_parm, test_ct_parm)
    t.RunTest()


