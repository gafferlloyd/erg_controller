import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;

// Single persistent view; delegates drawing to the appropriate page based on gPageIdx.
class MainView extends WatchUi.View {

    private var _gauge   as GaugePage;
    private var _scatter as ScatterPage;
    private var _summary as SummaryPage;

    function initialize() {
        View.initialize();
        _gauge   = new GaugePage();
        _scatter = new ScatterPage();
        _summary = new SummaryPage();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        if (gPageIdx == 0) {
            _gauge.onUpdate(dc);
        } else if (gPageIdx == 1) {
            _scatter.onUpdate(dc);
        } else {
            _summary.onUpdate(dc);
        }
    }
}
