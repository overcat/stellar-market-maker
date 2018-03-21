import os
import time

from stellar_base.builder import Builder
from stellar_base.keypair import Keypair
from stellar_base.horizon import Horizon
from stellar_base.asset import Asset
from stellar_base.address import Address


class MarketMaker(object):
    def __init__(self, config):
        self.seed = os.environ.get('STELLAR_SEED') or config.get('stellar_seed')
        self.keypair = Keypair.from_seed(self.seed)
        self.address = self.keypair.address().decode()
        self.selling_asset = Asset(config['base_asset']['code'], config['base_asset']['issuer'])
        self.buying_asset = Asset(config['counter_asset']['code'], config['counter_asset']['issuer'])
        self.buying_amount = config['buying_amount']
        self.buying_rate = config['buying_rate']
        self.selling_amount = config['selling_amount']
        self.selling_rate = config['selling_rate']
        self.horizon_url = config['horizon']
        self.horizon = Horizon(config['horizon'])
        self.network = 'public'

    def get_price(self):
        # 设定初始价格，需要改进，比如考虑深度之类的
        params = {
            "selling_asset_type": self.selling_asset.type,
            "selling_asset_code": self.selling_asset.code,
            "selling_asset_issuer": self.selling_asset.issuer,
            "buying_asset_type": self.buying_asset.type,
            "buying_asset_code": self.buying_asset.code,
            "buying_asset_issuer": self.buying_asset.issuer
        }
        data = self.horizon.order_book(params=params)
        # {'bid': '1.5310000', 'ask': '1.6000000'} 买一价与卖一价
        return {'bid': data['bids'][0]['price'], 'ask': data['asks'][0]['price']}

    def get_account_data(self):
        account = Address(address=self.address, network=self.network, horizon=self.horizon_url)
        account.get()
        return account

    def get_balance(self):
        handled_balance = {}
        balances_data = self.get_account_data().balances
        for balance in balances_data:
            if balance['asset_type'] == 'native':
                handled_balance['XLM'] = balance['balance']
            elif (balance['asset_code'] == self.selling_asset.code and
                  balance['asset_issuer'] == self.selling_asset.issuer) or \
                    (balance['asset_code'] == self.buying_asset.code and
                     balance['asset_issuer'] == self.buying_asset.issuer):
                handled_balance[balance['asset_code']] = balance['balance']
        return handled_balance

    def handle_offers_data(self):
        handled_offers_data = []
        offers_data = self.get_account_data().offers()['_embedded']['records']
        for data in offers_data:
            if ((data['selling']['asset_type'] == 'native' and self.selling_asset.type == 'native') or data['selling'][
                'asset_code'] == self.selling_asset.code and data['selling'][
                    'asset_issuer'] == self.selling_asset.issuer) and (
                    (data['buying']['asset_type'] == 'native' and self.buying_asset.type == 'native') or data['buying'][
                'asset_code'] == self.buying_asset.code and data['buying']['asset_issuer'] == self.buying_asset.issuer):
                handled_offer = {
                    'id': data['id'],
                    'amount': data['amount'],
                    'price': data['price'],
                    'type': 'selling'
                }

            if ((data['buying']['asset_type'] == 'native' and self.selling_asset.type == 'native') or data['buying'][
                'asset_code'] == self.selling_asset.code and data['buying'][
                    'asset_issuer'] == self.selling_asset.issuer) and (
                    (data['selling']['asset_type'] == 'native' and self.buying_asset.type == 'native') or
                    data['selling']['asset_code'] == self.buying_asset.code and data['selling'][
                        'asset_issuer'] == self.buying_asset.issuer):
                real_price = data['price_r']['d'] / data['price_r']['n']
                format_price = '{:0,.7f}'.format(real_price)
                format_amount = '{:0,.7f}'.format(
                    float(data['amount']) / real_price)
                handled_offer = {
                    'id': data['id'],
                    'amount': format_amount,
                    'price': format_price,
                    'type': 'buying'
                }
            handled_offers_data.append(handled_offer)
        return handled_offers_data

    def create_offers(self):
        market_price = self.get_price()
        builder = Builder(secret=self.seed, network=self.network, horizon=self.horizon_url)
        # 卖出 base_asset
        selling_price = round(float(market_price['ask']) * (1 + self.selling_rate), 7)
        builder.append_manage_offer_op(selling_code=self.selling_asset.code, selling_issuer=self.selling_asset.issuer,
                                       buying_code=self.buying_asset.code,
                                       buying_issuer=self.buying_asset.issuer,
                                       amount=self.selling_amount, price=selling_price)
        # 买入 base_asset
        buying_tmp_price = float(market_price['bid']) * (1 - self.buying_rate)
        buying_price = round(1 / buying_tmp_price, 7)
        buying_amount = round(self.buying_amount * buying_tmp_price, 7)
        builder.append_manage_offer_op(selling_code=self.buying_asset.code,
                                       selling_issuer=self.buying_asset.issuer,
                                       buying_code=self.selling_asset.code,
                                       buying_issuer=self.selling_asset.issuer,
                                       amount=buying_amount,
                                       price=buying_price)
        builder.sign()
        builder.submit()

    def cancel_all_offers(self):
        offers = self.handle_offers_data()
        builder = Builder(secret=self.seed, network=self.network, horizon=self.horizon_url)
        for offer in offers:
            builder.append_manage_offer_op(selling_code=self.selling_asset.code,
                                           selling_issuer=self.selling_asset.issuer,
                                           buying_code=self.buying_asset.code,
                                           buying_issuer=self.buying_asset.issuer,
                                           amount='0',
                                           price='1',
                                           offer_id=offer['id'])
        builder.sign()
        builder.submit()

    def print_offer(self):
        offers = self.handle_offers_data()
        for offer in offers:
            print("{type} {amount} {base_asset}, {price} {counter_asset}/{base_asset}".format(
                base_asset=self.selling_asset.code, counter_asset=self.buying_asset.code, **offer))

    def start(self):
        print("Your address: " + self.address)
        print(self.get_balance())

        self.cancel_all_offers()

        while True:
            try:
                offers = self.handle_offers_data()
                if len(offers) != 0:
                    time.sleep(3)
                else:
                    self.create_offers()
                    print("New offers created")
                    self.print_offer()
            except Exception as e:
                print(e)
