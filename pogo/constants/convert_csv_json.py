import csv
import json
import numpy as np

fieldnames = ['Id', 'Attack', 'Defense', 'Stamina', 'Name']
result_id = {}
result_name = {}
name_id = {}
id_name = {}
with open('basestats.csv', 'r') as c:
    reader = csv.DictReader(c, fieldnames)
    reader.next()
    for row in reader:
        id = row['Id']
        name = row['Name']
        del row['Id']
        del row['Name']
        result_id[id] = row
        result_name[name] = row
        name_id[name] = id
        id_name[id] = name
    with open('basestats_name.json', 'w') as j:
        json.dump(result_name, j)
    with open('basestats_id.json', 'w') as j:
        json.dump(result_id, j)
    with open('name_id.json', 'w') as j:
        json.dump(name_id, j)
    with open('id_name.json', 'w') as j:
        json.dump(id_name, j)

def two_column_csv_to_json(filename, cast_type):
    with open(filename + '.csv', 'r') as c:
        result = {}
        reader = csv.reader(c)
        for row in reader:
            result[cast_type(row[0])] = cast_type(row[1])
        print result
        with open(filename + '.json', 'w') as j:
            json.dump(result, j)


two_column_csv_to_json('./stardust', np.int)
two_column_csv_to_json('./cpmultiplier', np.float)
