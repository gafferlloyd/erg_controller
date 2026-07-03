import Toybox.Application;
import Toybox.WatchUi;
import Toybox.Lang;

class DynamicsApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
    }

    function onStop(state as Dictionary?) as Void {
    }

    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new DynamicsDashboardField()];
    }
}
