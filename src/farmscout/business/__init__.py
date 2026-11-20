"""What small businesses a property could host (venue, food, wellness) and how secluded it is."""

from farmscout.business.assessor import BusinessFitAssessor, Fit
from farmscout.business.setting import SettingDetector
from farmscout.business.uses import BusinessUse, BusinessUseCatalog

__all__ = ["BusinessFitAssessor", "BusinessUse", "BusinessUseCatalog", "Fit", "SettingDetector"]
