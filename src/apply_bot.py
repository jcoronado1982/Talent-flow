
import os
import sys
from src.app.bots.apply.supervisor import ApplyBotSupervisor

if __name__ == "__main__":
    bot = ApplyBotSupervisor(headless=False)
    bot.run()
