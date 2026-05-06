import baostock as bs
import pandas as pd

lg = bs.login()
print("login error_code:", lg.error_code)
print("login error_msg:", lg.error_msg)

rs = bs.query_history_k_data_plus(
    "sh.600519",
    "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM",
    start_date="2026-04-30",
    end_date="2026-04-30",
    frequency="d",
    adjustflag="3"
)

print("query error_code:", rs.error_code)
print("query error_msg:", rs.error_msg)

data_list = []
while rs.error_code == "0" and rs.next():
    data_list.append(rs.get_row_data())

df = pd.DataFrame(data_list, columns=rs.fields)
print(df)

bs.logout()