import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DBUS_IFACE = `
<node>
  <interface name="org.omnimouse.Studio.Focus">
    <method name="GetFocusedWindow">
      <arg type="s" direction="out" name="app_id"/>
      <arg type="s" direction="out" name="wm_class"/>
      <arg type="s" direction="out" name="title"/>
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="app_id"/>
      <arg type="s" name="wm_class"/>
      <arg type="s" name="title"/>
    </signal>
  </interface>
</node>`;

export default class OmniFocusExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/omnimouse/Studio/Focus');
        this._ownerId = Gio.bus_own_name_on_connection(
            Gio.DBus.session,
            'org.omnimouse.Studio.Focus',
            Gio.BusNameOwnerFlags.NONE,
            null,
            null
        );
        this._titleSignalId = 0;
        this._trackedWin = null;
        this._focusSignalId = global.display.connect('notify::focus-window', () => {
            this._onFocusChanged();
        });
        this._onFocusChanged();
    }

    disable() {
        if (this._focusSignalId) {
            global.display.disconnect(this._focusSignalId);
            this._focusSignalId = 0;
        }
        this._disconnectWindow();
        if (this._ownerId) {
            Gio.bus_unown_name(this._ownerId);
            this._ownerId = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
    }

    _disconnectWindow() {
        if (this._trackedWin && this._titleSignalId) {
            try {
                this._trackedWin.disconnect(this._titleSignalId);
            } catch (_e) {}
        }
        this._trackedWin = null;
        this._titleSignalId = 0;
    }

    _readCurrent() {
        const win = global.display.focus_window;
        if (!win)
            return ['', '', ''];
        let appId = '';
        try {
            const tracker = Shell.WindowTracker.get_default();
            const app = tracker ? tracker.get_window_app(win) : null;
            if (app)
                appId = app.get_id() || '';
        } catch (_e) {}
        const wmClass = win.get_wm_class() || '';
        const title = win.get_title() || '';
        return [appId, wmClass, title];
    }

    _emitCurrent() {
        if (!this._dbus)
            return;
        const [appId, wmClass, title] = this._readCurrent();
        try {
            this._dbus.emit_signal(
                'FocusChanged',
                new GLib.Variant('(sss)', [appId, wmClass, title])
            );
        } catch (_e) {}
    }

    _onFocusChanged() {
        this._disconnectWindow();
        const win = global.display.focus_window;
        if (win) {
            this._trackedWin = win;
            this._titleSignalId = win.connect('notify::title', () => this._emitCurrent());
        }
        this._emitCurrent();
    }

    GetFocusedWindow() {
        return this._readCurrent();
    }
}
