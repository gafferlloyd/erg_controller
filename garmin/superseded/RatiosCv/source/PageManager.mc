import Toybox.WatchUi;
import Toybox.Lang;

var gPageIdx as Number = 0;

// Single delegate handles Up/Down; the one MainView checks gPageIdx to decide what to draw.
class PageManager extends WatchUi.BehaviorDelegate {

    private const NUM_PAGES = 3;

    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onNextPage() as Boolean {
        gPageIdx = (gPageIdx + 1) % NUM_PAGES;
        WatchUi.requestUpdate();
        return true;
    }

    function onPreviousPage() as Boolean {
        gPageIdx = (gPageIdx + NUM_PAGES - 1) % NUM_PAGES;
        WatchUi.requestUpdate();
        return true;
    }
}
