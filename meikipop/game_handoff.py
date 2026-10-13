# meikipop/game_handoff.py
"""Lets a launcher that finds Meikipop already running hand it a new game.

VN Library couch mode starts Meikipop with --game-pid; when Meikipop is already open it posts
this distributed notification instead, with userInfo {"pid": <game pid>}.
"""
import logging
import sys

logger = logging.getLogger(__name__)

NOTIFICATION = "local.gustav.meikipop.followGame"


def listen_for_game_handoff(screen_manager):
    """Returns the observer; keep a reference to it for as long as it should listen."""
    if sys.platform != 'darwin':
        return None
    try:
        from Foundation import NSObject, NSDistributedNotificationCenter
        from Foundation import NSNotificationSuspensionBehaviorDeliverImmediately

        class GameHandoffObserver(NSObject):
            def followGame_(self, notification):
                try:
                    pid = int((notification.userInfo() or {}).get("pid", 0))
                except (TypeError, ValueError):
                    pid = 0
                if pid > 0:
                    screen_manager.follow_game(pid)

        observer = GameHandoffObserver.alloc().init()
        # Deliver while Meikipop is in the background, which is always the case here.
        NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_suspensionBehavior_(
            observer, b'followGame:', NOTIFICATION, None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        return observer
    except Exception as e:
        logger.warning("Game handoff from launchers is unavailable: %s", e)
        return None
