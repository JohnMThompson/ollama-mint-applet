const Applet = imports.ui.applet;
const ByteArray = imports.byteArray;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Lang = imports.lang;
const Pango = imports.gi.Pango;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
imports.gi.versions.Soup = "3.0";
const Soup = imports.gi.Soup;
const St = imports.gi.St;
const Util = imports.misc.util;

const DEFAULT_SERVER_URL = "http://127.0.0.1:3000";
const DEFAULT_MODEL = "mistral";
const POPUP_CONTENT_WIDTH = 406;
const MESSAGE_CONTENT_WIDTH = 386;
const PROMPT_CONTENT_WIDTH = 384;

class LocalMistralChatApplet extends Applet.TextApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);

        this.metadata = metadata;
        this.messages = [];
        this.model = DEFAULT_MODEL;
        this.modelNames = [];
        this.serverUrl = DEFAULT_SERVER_URL;
        this.modelName = DEFAULT_MODEL;
        this.activeMessage = null;
        this.activeRequest = null;
        this.isGenerating = false;

        this.set_applet_label("✨");
        this.set_applet_tooltip("Local Mistral Chat");

        this.httpSession = new Soup.Session();
        this.usesSoup3 = typeof this.httpSession.send_and_read_async === "function";
        this.httpSession.timeout = 300;
        this.httpSession.idle_timeout = 300;

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menu.setCustomStyleClass("local-mistral-chat-popup");
        this.menuManager.addMenu(this.menu);

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instanceId);
        this.settings.bind("server-url", "serverUrl");
        this.settings.bind("model-name", "modelName");
        this.settings.connect("changed::server-url", Lang.bind(this, this._onSettingsChanged));
        this.settings.connect("changed::model-name", Lang.bind(this, this._onSettingsChanged));

        this._buildMenu();
        this._onSettingsChanged();
    }

    on_applet_clicked() {
        this.menu.toggle();
        if (this.menu.isOpen) {
            this._loadModels();
            this._focusPrompt();
        }
    }

    on_applet_removed_from_panel() {
        this._cancelActiveRequest();
        this.settings.finalize();
    }

    _buildMenu() {
        this.root = new St.BoxLayout({
            vertical: true,
            style_class: "local-mistral-chat-root"
        });

        let header = new St.BoxLayout({
            vertical: true,
            style_class: "local-mistral-chat-header"
        });

        this.titleLabel = new St.Label({
            text: "Local Mistral Chat",
            style_class: "local-mistral-chat-title",
            width: POPUP_CONTENT_WIDTH
        });
        this.statusLabel = new St.Label({
            text: "Checking Ollama...",
            style_class: "local-mistral-chat-status",
            width: POPUP_CONTENT_WIDTH
        });
        this.statusLabel.clutter_text.line_wrap = true;
        this.statusLabel.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        header.add_actor(this.titleLabel);
        header.add_actor(this.statusLabel);

        this.scrollView = new St.ScrollView({
            style_class: "local-mistral-chat-scroll",
            overlay_scrollbars: true,
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            width: POPUP_CONTENT_WIDTH
        });

        this.thread = new St.BoxLayout({
            vertical: true,
            style_class: "local-mistral-chat-thread"
        });
        this.scrollView.add_actor(this.thread);

        this.prompt = new St.Entry({
            name: "local-mistral-chat-prompt",
            hint_text: "Ask a question...",
            can_focus: true,
            style_class: "local-mistral-chat-prompt",
            width: PROMPT_CONTENT_WIDTH
        });
        this.prompt.clutter_text.set_single_line_mode(false);
        this.prompt.clutter_text.connect("key-press-event", Lang.bind(this, this._onPromptKeyPress));

        let controls = new St.BoxLayout({
            style_class: "local-mistral-chat-controls",
            width: POPUP_CONTENT_WIDTH
        });

        this.sendButton = new St.Button({
            label: "Send",
            style_class: "local-mistral-chat-button local-mistral-chat-button-primary",
            can_focus: true
        });
        this.sendButton.connect("clicked", Lang.bind(this, this._sendPrompt));

        this.stopButton = new St.Button({
            label: "Stop",
            style_class: "local-mistral-chat-button",
            can_focus: true,
            visible: false
        });
        this.stopButton.connect("clicked", Lang.bind(this, this._stopGeneration));

        this.clearButton = new St.Button({
            label: "Clear",
            style_class: "local-mistral-chat-button",
            can_focus: true
        });
        this.clearButton.connect("clicked", Lang.bind(this, this._clearChat));

        this.openButton = new St.Button({
            label: "Open Full Chat",
            style_class: "local-mistral-chat-button",
            can_focus: true
        });
        this.openButton.connect("clicked", Lang.bind(this, this._openFullChat));

        controls.add_actor(this.sendButton);
        controls.add_actor(this.stopButton);
        controls.add_actor(this.clearButton);
        controls.add_actor(this.openButton);

        this.root.add_actor(header);
        this.root.add_actor(this.scrollView);
        this.root.add_actor(this.prompt);
        this.root.add_actor(controls);
        this.menu.addActor(this.root);

        this._renderMessages();
    }

    _onPromptKeyPress(actor, event) {
        let symbol = event.get_key_symbol();
        let state = event.get_state();
        let shiftPressed = (state & Clutter.ModifierType.SHIFT_MASK) !== 0;
        if ((symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter) && !shiftPressed) {
            this._sendPrompt();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _focusPrompt() {
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 120, Lang.bind(this, function() {
            if (this.prompt) {
                global.stage.set_key_focus(this.prompt.clutter_text);
            }
            return GLib.SOURCE_REMOVE;
        }));
    }

    _onSettingsChanged() {
        this.serverUrl = this._cleanServerUrl(this.serverUrl);
        this.modelName = (this.modelName || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
        this.model = this.modelName;
        this._loadModels();
    }

    _cleanServerUrl(value) {
        let cleaned = (value || DEFAULT_SERVER_URL).trim();
        while (cleaned.length > 1 && cleaned[cleaned.length - 1] === "/") {
            cleaned = cleaned.slice(0, -1);
        }
        return cleaned || DEFAULT_SERVER_URL;
    }

    _loadModels() {
        this._request("GET", this.serverUrl + "/api/models", null, Lang.bind(this, function(status, body) {
            if (status < 200 || status >= 300) {
                this.statusLabel.set_text("Server unavailable at " + this.serverUrl);
                return;
            }

            try {
                let data = JSON.parse(body);
                if (data.error) {
                    this.statusLabel.set_text(data.error);
                    return;
                }

                let names = (data.models || []).map(function(model) {
                    return model.name;
                }).filter(function(name) {
                    return !!name;
                });
                this.modelNames = names;
                this.model = this._resolveModelName(this.modelName || data.defaultModel || DEFAULT_MODEL, names);
                this._syncModelOptions();
                if (names.length && this.model !== this.modelName) {
                    this.modelName = this.model;
                    this.settings.setValue("model-name", this.model);
                }
                this.statusLabel.set_text(names.length
                    ? "Connected to Ollama (" + names.length + " model" + (names.length === 1 ? "" : "s") + ", using " + this.model + ")"
                    : "Connected to Ollama");
            } catch (e) {
                this.statusLabel.set_text("Invalid response from local server");
            }
        }));
    }

    _syncModelOptions() {
        let options = {};
        let names = this.modelNames.slice();
        if (names.indexOf(this.model) < 0) {
            names.unshift(this.model);
        }

        for (let i = 0; i < names.length; i++) {
            options[names[i]] = names[i];
        }

        this.settings.setOptions("model-name", options);
    }

    _resolveModelName(preferred, names) {
        if (names.indexOf(preferred) >= 0) {
            return preferred;
        }

        for (let i = 0; i < names.length; i++) {
            if (names[i] === preferred + ":latest" || names[i].indexOf(preferred + ":") === 0) {
                return names[i];
            }
        }
        return preferred;
    }

    _sendPrompt() {
        if (this.isGenerating) {
            return;
        }

        let text = this.prompt.get_text().trim();
        if (!text) {
            return;
        }

        this.prompt.set_text("");
        this.messages.push({ role: "user", content: text });
        this.activeMessage = { role: "assistant", content: "" };
        this.messages.push(this.activeMessage);
        this._setGenerating(true);
        this._renderMessages();

        let payload = {
            model: this.model || this.modelName || DEFAULT_MODEL,
            messages: this.messages.filter(function(message) {
                return !!message.content;
            }).slice(-16),
            options: { temperature: 0.7 }
        };

        this.activeRequest = this._request("POST", this.serverUrl + "/api/chat", JSON.stringify(payload), Lang.bind(this, function(status, body) {
            if (!this.activeMessage) {
                return;
            }

            if (status < 200 || status >= 300) {
                this.activeMessage.content = "Error: chat request failed (" + status + ")";
            } else {
                this.activeMessage.content = this._parseChatResponse(body);
            }

            this._setGenerating(false);
            this._renderMessages();
            this.activeMessage = null;
            this.activeRequest = null;
        }));
    }

    _parseChatResponse(body) {
        let content = "";
        let lines = body.split("\n");

        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            if (!line) {
                continue;
            }

            try {
                let data = JSON.parse(line);
                if (data.error) {
                    return "Error: " + data.error;
                }
                if (data.message && data.message.content) {
                    content += data.message.content;
                }
            } catch (e) {
                return body.trim() || "Error: invalid chat response";
            }
        }

        return content.trim() || "No response.";
    }

    _request(method, url, body, callback) {
        let message = Soup.Message.new(method, url);
        if (!message) {
            callback(0, "");
            return null;
        }

        if (this.usesSoup3) {
            let cancellable = new Gio.Cancellable();
            if (body !== null) {
                message.get_request_headers().append("Content-Type", "application/json");
                message.set_request_body_from_bytes("application/json", new GLib.Bytes(ByteArray.fromString(body)));
            }

            this.httpSession.send_and_read_async(message, GLib.PRIORITY_DEFAULT, cancellable, Lang.bind(this, function(session, result) {
                let responseBody = "";
                try {
                    let bytes = session.send_and_read_finish(result);
                    if (bytes) {
                        responseBody = ByteArray.toString(ByteArray.fromGBytes(bytes));
                    }
                } catch (e) {
                    if (!cancellable.is_cancelled()) {
                        callback(0, "Error: " + e.message);
                    }
                    return;
                }
                callback(message.get_status() || 0, responseBody);
            }));

            return {
                cancel: function() {
                    cancellable.cancel();
                }
            };
        }

        if (body !== null) {
            message.request_headers.append("Content-Type", "application/json");
            message.set_request("application/json", Soup.MemoryUse.COPY, body, body.length);
        }

        this.httpSession.queue_message(message, Lang.bind(this, function(session, response) {
            let responseBody = "";
            if (response.response_body && response.response_body.data) {
                responseBody = response.response_body.data;
            }
            callback(response.status_code || 0, responseBody);
        }));

        return {
            cancel: Lang.bind(this, function() {
                this.httpSession.cancel_message(message, Soup.Status.CANCELLED);
            })
        };
    }

    _stopGeneration() {
        this._cancelActiveRequest();
        if (this.activeMessage && !this.activeMessage.content) {
            this.activeMessage.content = "Stopped.";
        }
        this._setGenerating(false);
        this._renderMessages();
        this.activeMessage = null;
    }

    _cancelActiveRequest() {
        if (this.activeRequest) {
            this.activeRequest.cancel();
            this.activeRequest = null;
        }
    }

    _clearChat() {
        this._cancelActiveRequest();
        this.messages = [];
        this.activeMessage = null;
        this._setGenerating(false);
        this._renderMessages();
    }

    _openFullChat() {
        Util.spawnCommandLine("xdg-open " + this.serverUrl);
        this.menu.close();
    }

    _setGenerating(isGenerating) {
        this.isGenerating = isGenerating;
        this.sendButton.reactive = !isGenerating;
        this.stopButton.visible = isGenerating;
    }

    _renderMessages() {
        this.thread.destroy_all_children();

        if (!this.messages.length) {
            this.thread.add_actor(new St.Label({
                text: "Ask a question to start a quick chat.",
                style_class: "local-mistral-chat-empty",
                width: MESSAGE_CONTENT_WIDTH
            }));
            return;
        }

        for (let i = 0; i < this.messages.length; i++) {
            this.thread.add_actor(this._messageActor(this.messages[i]));
        }

        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, Lang.bind(this, function() {
            let adjustment = this.scrollView.get_vscroll_bar().get_adjustment();
            adjustment.set_value(adjustment.upper - adjustment.page_size);
            return GLib.SOURCE_REMOVE;
        }));
    }

    _messageActor(message) {
        let item = new St.BoxLayout({
            vertical: true,
            style_class: "local-mistral-chat-message",
            width: MESSAGE_CONTENT_WIDTH
        });

        item.add_actor(new St.Label({
            text: message.role === "assistant" ? "Assistant" : "You",
            style_class: "local-mistral-chat-role"
        }));

        let bubble = new St.Label({
            text: message.content || "...",
            style_class: "local-mistral-chat-bubble" + (message.role === "user" ? " local-mistral-chat-bubble-user" : ""),
            width: MESSAGE_CONTENT_WIDTH
        });
        bubble.clutter_text.line_wrap = true;
        bubble.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        bubble.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        item.add_actor(bubble);

        return item;
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    return new LocalMistralChatApplet(metadata, orientation, panelHeight, instanceId);
}
