#!/python3

import re
import json
import datetime

import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.products import Products
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_get_response import ItemGetResponse
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_response import TransactionsGetResponse
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_response import AccountsGetResponse
from typing import Optional, List


class AccountBalance:
    def __init__(self, data: AccountsGetResponse):
        self.raw_data = data.__dict__
        self.account_id        = data.account_id
        self.account_name      = data.name
        self.account_type      = data.type
        self.account_subtype   = data.subtype
        self.account_number    = data.mask
        self.balance_current   = data.balances.current
        self.balance_available = data.balances.available
        self.balance_limit     = data.balances.limit
        self.currency_code     = data.balances.iso_currency_code


class AccountInfo:
    def __init__(self, data: ItemGetResponse):
        self.raw_data = data.__dict__
        self.item_id                   = data.item.item_id
        self.institution_id            = data.item.institution_id
        self.ts_consent_expiration     = data.item.consent_expiration_time
        self.ts_last_failed_update     = data.status.transactions.last_failed_update
        self.ts_last_successful_update = data.status.transactions.last_successful_update


class Transaction:
    def __init__(self, data: TransactionsGetResponse):
        self.raw_data = data.__dict__
        self.account_id     = data.account_id
        self.date           = data.date
        self.transaction_id = data.transaction_id
        self.pending        = data.pending
        self.merchant_name  = data.merchant_name
        self.amount         = data.amount
        self.currency_code  = data.iso_currency_code

    def __str__(self):
        return "%s %s %s - %4.2f %s" % ( self.date, self.transaction_id, self.merchant_name, self.amount, self.currency_code )


def raise_plaid(ex: plaid.ApiException):
    response = json.loads(ex.body)
    if response['error_code'] == 'NO_ACCOUNTS':
        raise PlaidNoApplicableAccounts(response)
    elif response['error_code'] == 'ITEM_LOGIN_REQUIRED':
        raise PlaidAccountUpdateNeeded(response)
    else:
        raise PlaidUnknownError(response)


def wrap_plaid_error(f):
    def wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except plaid.ApiException as ex:
            raise_plaid(ex)
    return wrap


class PlaidError(Exception):
    def __init__(self, plaid_error):
        super().__init__()
        self.error_code = plaid_error["error_code"]
        self.error_message = plaid_error["error_message"]

    def __str__(self):
        return "%s: %s" % (self.error_code, self.error_message)


class PlaidUnknownError(PlaidError):
    pass


class PlaidNoApplicableAccounts(PlaidError):
    pass


class PlaidAccountUpdateNeeded(PlaidError):
    pass


class PlaidAPI():
    def __init__(self, configuration: plaid.Configuration):
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)

    @wrap_plaid_error
    def get_link_token(self, access_token=None) -> str:
        """
        Calls the /link/token/create workflow, which returns an access token
        which can be used to initate the account linking process or, if an access_token
        is provided, to update an existing linked account.

        This token is used by the web-browser/JavaScript API to exchange for a public
        token to finalize the linking process.

        https://plaid.com/docs/api/tokens/#token-exchange-flow
        """

        data = {
            'user': {
                'client_user_id': 'abc123',
            },
            'client_name': 'plaid-sync',
            'country_codes': [CountryCode('US')],
            'language': 'en',
        }

        # if updating an existing account, the products field is not allowed
        if access_token:
            data['access_token'] = access_token
        else:
            data['products'] = [Products('transactions')]

        req = LinkTokenCreateRequest(**data)
        res = self.client.link_token_create(req)
        return res.link_token

    @wrap_plaid_error
    def exchange_public_token(self, public_token: str) -> str:
        """
        Exchange a temporary public token for a permanent private
        access token.
        """
        req = ItemPublicTokenExchangeRequest(public_token)
        res = self.client.item_public_token_exchange(req)
        return res.access_token

    @wrap_plaid_error
    def sandbox_reset_login(self, access_token: str) -> str:
        """
        Only applicable to sandbox environment. Resets the login
        details for a specific account so you can test the update
        account flow.

        Otherwise, attempting to update will just display "Account
        already connected." in the Plaid browser UI.
        """
        return self.client.post('/sandbox/item/reset_login', {
            'access_token': access_token,
        })

    @wrap_plaid_error
    def get_item_info(self, access_token: str)->AccountInfo:
        """
        Returns account information associated with this particular access token.
        """
        req = ItemGetRequest(access_token=access_token)
        ItemGetResponse = self.client.item_get(req)
        return AccountInfo(ItemGetResponse)

    @wrap_plaid_error
    def get_account_balance(self, access_token:str)->List[AccountBalance]:
        """
        Returns the balances of all accounts associated with this particular access_token.
        """
        req = AccountsBalanceGetRequest(access_token=access_token)
        res = self.client.accounts_balance_get(req)
        return list( map( AccountBalance, res.accounts ) )

    @wrap_plaid_error
    def get_transactions(self, access_token:str, start_date:datetime.date, end_date:datetime.date, account_ids:Optional[List[str]]=None, status_callback=None):
        ret = []
        total_transactions = None
        while True:
            req = TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date
            )
            res = self.client.transactions_get(req)

            total_transactions = res.total_transactions

            ret += [
                Transaction(t)
                for t in res.transactions
            ]

            if status_callback: status_callback(len(ret), total_transactions)
            if len(ret) >= total_transactions: break

        return ret
