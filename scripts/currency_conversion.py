# coding: utf-8
change_account = lambda account_id: requests.post(f"https://localhost:5000/v1/api/iserver/account", json={"acctId": account_id},verify=False).json()
buy_usd  = lambda amount_in_shekel: {'orders': [{'acctId': 'U3492785',
   'cOID': f'{amount_in_shekel}ILS -> USD',
   'conid': 44495102,
   'isCcyConv': True,
   'orderType': 'MKT',
   'fxQty': amount_in_shekel,
   'side': 'BUY',
   'tif': 'DAY',
   'ticker': 'USD.ILS'
   }]}
create_buy_order = lambda account_id: requests.post(f"https://localhost:5000/v1/api/iserver/account/{account_id}/orders", json=data, verify=False).json()
authenticate_trading = lambda: requests.post(f"https://127.0.0.1:5000/v1/api/iserver/auth/ssodh/init?publish=true&compete=true", verify=False).json()
get_current_ils = lambda account_id: requests.get(f"https://localhost:5000/v1/api/portfolio/{account_id}/ledger",verify=False).json()["ILS"]["settledcash"]
