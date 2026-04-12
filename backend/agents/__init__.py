# backend/agents/__init__.py
# Exports all agent classes for easy importing.

from .email_agent        import EmailAgent
from .calendar_agent     import CalendarAgent
from .file_agent         import FileAgent
from .screen_agent       import ScreenAgent
from .web_agent          import WebAgent
from .data_agent         import DataAgent
from .messaging_agent    import MessagingAgent
from .smart_home_agent   import SmartHomeAgent
from .finance_agent      import FinanceAgent
from .productivity_agent import ProductivityAgent

__all__ = [
    "EmailAgent", "CalendarAgent", "FileAgent",
    "ScreenAgent", "WebAgent", "DataAgent",
    "MessagingAgent", "SmartHomeAgent", "FinanceAgent",
    "ProductivityAgent"
]