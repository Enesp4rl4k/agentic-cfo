# Banks package — importing this package registers all parsers via @register decorator.
from app.parsers.banks.akbank import AkbankParser
from app.parsers.banks.garanti import GarantiParser
from app.parsers.banks.isbank import IsBankParser
from app.parsers.banks.ziraat import ZiraatParser

__all__ = ["AkbankParser", "GarantiParser", "IsBankParser", "ZiraatParser"]
