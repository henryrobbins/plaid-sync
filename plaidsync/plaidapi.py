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
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_response import TransactionsSyncResponse
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_response import AccountsGetResponse
from plaid.model.account_base import AccountBase
from plaid.model import transaction
from plaid.model.item import Item
from typing import Optional, List


class AccountBalance:
    def __init__(self, data: AccountBase):
        self.raw_data = serialize_account_base(data)
        self.account_id        = data.account_id
        self.account_name      = data.name
        self.account_type      = str(data.type)
        self.account_subtype   = str(data.subtype)
        self.account_number    = data.mask
        self.balance_current   = data.balances.current
        self.balance_available = data.balances.available
        self.balance_limit     = data.balances.limit
        self.currency_code     = data.balances.iso_currency_code


class AccountInfo:
    def __init__(self, data: ItemGetResponse):
        self.raw_data = serialize_item(data.item)
        self.item_id                   = data.item.item_id
        self.institution_id            = data.item.institution_id
        self.ts_consent_expiration     = data.item.consent_expiration_time
        self.ts_last_failed_update     = data.status.transactions.last_failed_update
        self.ts_last_successful_update = data.status.transactions.last_successful_update


class Transaction:
    def __init__(self, data: plaid.model.transaction.Transaction):
        self.raw_data = serialize_transaction(data)
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
        transactions = []
        has_more = True
        next_cursor = ""
        while has_more:
            req = TransactionsSyncRequest(
                access_token=access_token,
                cursor=next_cursor
            )
            res = self.client.transactions_sync(req)
            has_more = res.has_more
            next_cursor = res.next_cursor
            added = res.added
            transactions += [Transaction(t) for t in added]
        return transactions


# def serialize_account_get_response(obj: AccountsGetResponse):
#     data = {}
#     print(obj)
#     data["accounts"] = [serialize_account_base(account) for account in obj.accounts]
#     data["item"] = serialize_item(obj.item)
#     data["request_id"] = obj.request_id
#     data["payment_risk_assessment"] = obj.payment_risk_assessment.__dict__
#     return data

def serialize_account_base(obj: AccountBase):
    data = {}
    data["account_id"] = obj.account_id
    data["balances"] = obj.balances.to_dict()
    data["mask"] = obj.mask
    data["name"] = obj.name
    data["official_name"] = obj.official_name
    data["type"] = str(obj.type)
    data["subtype"] = str(obj.subtype)
    data["verification_status"] = obj.get("verification_status", None)
    data["persistent_account_id"] = obj.get("persistent_account_id", None)
    return data


def serialize_item(obj: Item):
    data = {}
    data["item_id"] = obj.item_id
    data["webhook"] = obj.webhook
    data["available_products"] = [str(p) for p in obj.available_products]
    data["billed_products"] = [str(p) for p in obj.billed_products]
    if obj.consent_expiration_time:
        data["consent_expiration_time"] = obj.consent_expiration_time.isoformat()
    else:
        data["consent_expiration_time"] = None
    data["update_type"] = obj.update_type
    data["institution_id"] = obj.institution_id
    data["products"] = [str(p) for p in obj.products]
    # print(obj.consented_products)
    # if obj.consented_products:
    #     data["consented_products"] = [str(p) for p in obj.consented_products]
    # else:
    #     data["consented_products"] = []
    return data

# def serialize_item_get_response(obj: ItemGetResponse):
#     data = []
#     data["item"] = serialize_item(obj.item)
#     data["request_id"] = obj.request_id
#     data[""]

#                 'item': (Item,),  # noqa: E501
#             'request_id': (str,),  # noqa: E501
#             'status': (ItemStatusNullable,),  # noqa: E501

def serialize_transaction(obj: transaction.Transaction):
    data = {}
    data["account_id"] = obj.account_id
    data["iso_currency_code"] = obj.iso_currency_code
    data["category"] = obj.category
    data["category_id"] = obj.category_id
    data["date"] = obj.date.isoformat()
    data["name"] = obj.name
    data["pending"] = obj.pending
    data["pending_transaction_id"] = obj.pending_transaction_id
    data["account_owner"] = obj.account_owner
    data["transaction_id"] = obj.transaction_id
    data["authorized_date"] = obj.authorized_date.isoformat()
    if obj.datetime:
        data["datetime"] = obj.datetime.isoformat()
    else:
        data["datetime"] = None
    data["payment_channel"] = obj.payment_channel
            # 'transaction_code': (TransactionCode,),  # noqa: E501
            # 'check_number': (str, none_type,),  # noqa: E501
            # 'merchant_name': (str, none_type,),  # noqa: E501
            # 'original_description': (str, none_type,),  # noqa: E501
            # 'transaction_type': (str,),  # noqa: E501
            # 'logo_url': (str, none_type,),  # noqa: E501
            # 'website': (str, none_type,),  # noqa: E501
            # 'personal_finance_category': (PersonalFinanceCategory,),  # noqa: E501
            # 'personal_finance_category_icon_url': (str,),  # noqa: E501
            # 'counterparties': ([TransactionCounterparty],),  # noqa: E501
            # 'merchant_entity_id': (str, none_type,),  # noqa: E501
