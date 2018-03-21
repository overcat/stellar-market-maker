from maker import MarketMaker
from config import xlm_xcn_config

market_maker = MarketMaker(xlm_xcn_config)
market_maker.start()
