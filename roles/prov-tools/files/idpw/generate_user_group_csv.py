import csv
import requests

base_url = 'http://idm3-bindbroker:8090/IDManager'
user_group_url = base_url + '/SystemUserGroupIF'
req_header = {'HTTP_SYSTEMACCOUNT': 'SYSTEM'}


if __name__=="__main__":
    user_group_req = requests.get(user_group_url, headers=req_header)
    user_group = user_group_req.json()
    with open('user_group.csv', mode='w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        header = ['sAMAccountName','gidNumber']
        writer.writerow(header)
        for ug in user_group:
            row = [
                ug['sAMAccountName'],
                ug['gidNumber'],
            ]
            writer.writerow(row)
