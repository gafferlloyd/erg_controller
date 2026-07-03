import Toybox.Application;
import Toybox.WatchUi;
import Toybox.Lang;

var gModel  as DataModel?  = null;
var gLoop   as SensorLoop? = null;

class RatiosCvApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
        var winSecs = Application.Properties.getValue("windowSecs") as Number;
        if (winSecs == null || winSecs < 1) { winSecs = 60; }
        gModel = new DataModel(winSecs);
        gLoop  = new SensorLoop(gModel);
        gLoop.start();
    }

    function onStop(state as Dictionary?) as Void {
        if (gLoop != null) { gLoop.stop(); }
    }

    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new MainView(), new PageManager()];
    }
}
