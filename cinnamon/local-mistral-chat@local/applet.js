const Applet = imports.ui.applet;
const ByteArray = imports.byteArray;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Lang = imports.lang;
const Main = imports.ui.main;
const Pango = imports.gi.Pango;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
imports.gi.versions.Soup = "3.0";
const Soup = imports.gi.Soup;
const St = imports.gi.St;
const Util = imports.misc.util;
let AppletStream = null;

const DEFAULT_SERVER_URL = "http://127.0.0.1:17865";
const LEGACY_SERVER_URL = "http://127.0.0.1:3000";
const DEFAULT_MODEL = "mistral";
const POPUP_CONTENT_WIDTH = 406;
const MESSAGE_CONTENT_WIDTH = 386;
const PROMPT_CONTENT_WIDTH = 384;
const PROMPT_MIN_HEIGHT = 54;
const PROMPT_MAX_HEIGHT = 112;

class PersistentPopupMenuManager extends PopupMenu.PopupMenuManager {
    _onKeyFocusChanged() {
        if (!this.grabbed || !this._activeMenu) {
            return;
        }

        let focus = global.stage.key_focus;
        if (focus && this._activeMenuContains(focus)) {
            return;
        }
    }

    _onEventCapture(actor, event) {
        if (!this.grabbed) {
            return Clutter.EVENT_PROPAGATE;
        }

        let activeMenuContains = this._eventIsOnActiveMenu(event);
        let eventType = event.type();

        if (!activeMenuContains && eventType === Clutter.EventType.BUTTON_PRESS) {
            this._ungrab();
            return Clutter.EVENT_PROPAGATE;
        }

        return super._onEventCapture(actor, event);
    }

    ensureInputGrab() {
        if (this.grabbed || !this._activeMenu) {
            return;
        }

        this._preGrabInputMode = global.stage_input_mode;
        this._grabbedFromKeynav = false;
        this._grab();
        this._activeMenu.actor.grab_key_focus();
    }
}

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
        this.activeMessageBubble = null;
        this.streamRenderSource = 0;
        this.isGenerating = false;
        this.isLoadingModel = false;
        this.hasActiveModel = false;

        this.set_applet_label("✨");
        this.set_applet_tooltip("Local LLM Chat");

        this.httpSession = new Soup.Session();
        this.usesSoup3 = typeof this.httpSession.send_and_read_async === "function";
        this.httpSession.timeout = 300;
        this.httpSession.idle_timeout = 300;

        this.menuManager = new PersistentPopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menu.setCustomStyleClass("local-mistral-chat-popup");
        this.menuManager.addMenu(this.menu);
        // Keep the persistent popup clickable after its modal grab is released.
        Main.layoutManager.addChrome(this.menu.actor, {
            affectsInputRegion: true,
            doNotAdd: true
        });

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
        this._cancelStreamRender();
        Main.layoutManager.untrackChrome(this.menu.actor);
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
            text: "Local LLM Chat",
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
        this.changeModelButton = new St.Button({
            label: "Change model",
            style_class: "local-mistral-chat-button local-mistral-chat-change-model",
            can_focus: true,
            visible: false
        });
        this.changeModelButton.connect("clicked", Lang.bind(this, function() {
            this._showModelChooser(this.modelNames, true);
        }));
        header.add_actor(this.changeModelButton);

        this.modelChooser = new St.BoxLayout({
            vertical: true,
            visible: false,
            style_class: "local-mistral-chat-model-dialog",
            width: POPUP_CONTENT_WIDTH
        });
        this.modelChooser.add_actor(new St.Label({
            text: "Load an Ollama model",
            style_class: "local-mistral-chat-model-dialog-title"
        }));
        let chooserDescription = new St.Label({
            text: "No model is currently running. Select a downloaded model to load before chatting.",
            style_class: "local-mistral-chat-model-dialog-description",
            width: MESSAGE_CONTENT_WIDTH
        });
        chooserDescription.clutter_text.line_wrap = true;
        chooserDescription.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        this.modelChooser.add_actor(chooserDescription);
        this.modelChoices = new St.BoxLayout({
            vertical: true,
            style_class: "local-mistral-chat-model-choices"
        });
        this.modelChooser.add_actor(this.modelChoices);

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
        this.prompt.clutter_text.set_line_wrap(true);
        this.prompt.clutter_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR);
        this.prompt.clutter_text.set_ellipsize(Pango.EllipsizeMode.NONE);
        this.prompt.set_clip_to_allocation(true);
        this.prompt.clutter_text.connect("text-changed", Lang.bind(this, this._resizePrompt));
        this.prompt.clutter_text.connect("key-press-event", Lang.bind(this, this._onPromptKeyPress));
        this.prompt.clutter_text.connect("button-press-event", Lang.bind(this, this._onPromptButtonPress));
        this._resizePrompt();

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
        this.root.add_actor(this.modelChooser);
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

    _onPromptButtonPress() {
        this.menuManager.ensureInputGrab();
        this._focusPrompt();
        return Clutter.EVENT_PROPAGATE;
    }

    _resizePrompt() {
        let textWidth = PROMPT_CONTENT_WIDTH - 20;
        let preferredHeight = this.prompt.clutter_text.get_preferred_height(textWidth)[1] + 18;
        this.prompt.set_height(Math.max(PROMPT_MIN_HEIGHT, Math.min(PROMPT_MAX_HEIGHT, preferredHeight)));
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
        if (this.serverUrl === LEGACY_SERVER_URL) {
            this.serverUrl = DEFAULT_SERVER_URL;
            this.settings.setValue("server-url", this.serverUrl);
        }
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
                if (data.activeModel) {
                    this.model = data.activeModel;
                    this.hasActiveModel = true;
                } else {
                    this.hasActiveModel = false;
                    this.model = this._resolveModelName(this.modelName || data.defaultModel || DEFAULT_MODEL, names);
                }
                this._syncModelOptions();
                this.changeModelButton.visible = names.length > 0 && this.hasActiveModel;
                if (data.activeModel && this.model !== this.modelName) {
                    this.modelName = this.model;
                    this.settings.setValue("model-name", this.model);
                }
                if (data.activeModel) {
                    this._hideModelChooser();
                    this.statusLabel.set_text("Using running model " + data.activeModel);
                } else {
                    this.statusLabel.set_text(names.length ? "No model running" : "No downloaded models");
                    this._showModelChooser(names, false);
                }
            } catch (e) {
                this.statusLabel.set_text("Invalid response from local server");
            }
        }));
    }

    _showModelChooser(names, allowCancel) {
        this.modelChoices.destroy_all_children();
        if (!names.length) {
            this.modelChoices.add_actor(new St.Label({
                text: "No downloaded models are available.",
                style_class: "local-mistral-chat-model-dialog-description"
            }));
        }
        for (let i = 0; i < names.length; i++) {
            let modelName = names[i];
            let button = new St.Button({
                label: modelName,
                style_class: "local-mistral-chat-button local-mistral-chat-model-choice",
                can_focus: true
            });
            button.connect("clicked", Lang.bind(this, function() {
                this._loadModel(modelName);
            }));
            this.modelChoices.add_actor(button);
        }
        if (allowCancel) {
            let cancelButton = new St.Button({
                label: "Cancel",
                style_class: "local-mistral-chat-button",
                can_focus: true
            });
            cancelButton.connect("clicked", Lang.bind(this, function() {
                this._hideModelChooser();
                this._focusPrompt();
            }));
            this.modelChoices.add_actor(cancelButton);
        }
        this.modelChooser.visible = true;
        this.scrollView.visible = false;
        this.prompt.visible = false;
        this.sendButton.reactive = false;
        this.changeModelButton.reactive = false;
    }

    _hideModelChooser() {
        this.isLoadingModel = false;
        this.modelChooser.visible = false;
        this.scrollView.visible = true;
        this.prompt.visible = true;
        this.sendButton.reactive = !this.isGenerating;
        this.changeModelButton.reactive = !this.isGenerating;
    }

    _loadModel(modelName) {
        if (this.isLoadingModel) {
            return;
        }
        this.isLoadingModel = true;
        this.statusLabel.set_text("Loading " + modelName + "...");
        let buttons = this.modelChoices.get_children();
        for (let i = 0; i < buttons.length; i++) {
            if (buttons[i] instanceof St.Button) {
                buttons[i].reactive = false;
            }
        }
        this._request("POST", this.serverUrl + "/api/models/load", JSON.stringify({
            model: modelName
        }), Lang.bind(this, function(status, body) {
            this.isLoadingModel = false;
            if (status < 200 || status >= 300) {
                let error = "Unable to load " + modelName;
                try {
                    error = JSON.parse(body).error || error;
                } catch (e) {
                    // Use the generic error.
                }
                this.statusLabel.set_text(error);
                this._showModelChooser(this.modelNames, this.hasActiveModel);
                return;
            }
            this.model = modelName;
            this.modelName = modelName;
            this.hasActiveModel = true;
            this.settings.setValue("model-name", modelName);
            this.changeModelButton.visible = true;
            this._hideModelChooser();
            this.statusLabel.set_text("Using running model " + modelName);
            this._focusPrompt();
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
        if (this.isGenerating || this.modelChooser.visible) {
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

        let parser = new AppletStream.NdjsonStreamParser(Lang.bind(this, function(content) {
            if (!this.activeMessage) {
                return;
            }
            this.activeMessage.content += content;
            this._scheduleStreamRender();
        }));

        let finish = Lang.bind(this, function(status, error) {
            if (!this.activeMessage) {
                return;
            }
            try {
                parser.finish();
            } catch (parseError) {
                error = parseError;
            }
            if (error) {
                this.activeMessage.content =
                    (this.activeMessage.content ? this.activeMessage.content + "\n\n" : "") +
                    "Error: " + error.message;
            } else if (status < 200 || status >= 300) {
                this.activeMessage.content = "Error: chat request failed (" + status + ")";
            } else if (!this.activeMessage.content.trim()) {
                this.activeMessage.content = "No response.";
            }
            this._flushStreamRender();
            this._setGenerating(false);
            this.activeMessage = null;
            this.activeRequest = null;
        });

        if (this.usesSoup3) {
            this.activeRequest = this._streamRequest(
                "POST",
                this.serverUrl + "/api/chat",
                JSON.stringify(payload),
                Lang.bind(this, function(line) {
                    parser.push(line + "\n");
                }),
                finish
            );
        } else {
            this.activeRequest = this._request(
                "POST",
                this.serverUrl + "/api/chat",
                JSON.stringify(payload),
                Lang.bind(this, function(status, body) {
                    let error = null;
                    try {
                        parser.push(body);
                    } catch (parseError) {
                        error = parseError;
                    }
                    finish(status, error);
                })
            );
        }
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

    _streamRequest(method, url, body, onLine, onComplete) {
        let message = Soup.Message.new(method, url);
        if (!message) {
            onComplete(0, new Error("Unable to create request"));
            return null;
        }
        let cancellable = new Gio.Cancellable();
        message.get_request_headers().append("Content-Type", "application/json");
        message.set_request_body_from_bytes(
            "application/json",
            new GLib.Bytes(ByteArray.fromString(body))
        );

        this.httpSession.send_async(
            message,
            GLib.PRIORITY_DEFAULT,
            cancellable,
            Lang.bind(this, function(session, result) {
                let input;
                try {
                    input = session.send_finish(result);
                } catch (error) {
                    if (!cancellable.is_cancelled()) {
                        onComplete(0, error);
                    }
                    return;
                }
                let dataInput = new Gio.DataInputStream({ base_stream: input });
                let completed = false;
                let complete = function(error) {
                    if (completed || cancellable.is_cancelled()) {
                        return;
                    }
                    completed = true;
                    onComplete(message.get_status() || 0, error || null);
                };
                let readNext = function() {
                    dataInput.read_line_async(
                        GLib.PRIORITY_DEFAULT,
                        cancellable,
                        function(stream, readResult) {
                            try {
                                let result = stream.read_line_finish_utf8(readResult);
                                let line = result[0];
                                if (line === null) {
                                    complete(null);
                                    return;
                                }
                                onLine(line);
                                readNext();
                            } catch (error) {
                                complete(error);
                            }
                        }
                    );
                };
                readNext();
            })
        );

        return {
            cancel: function() {
                cancellable.cancel();
            }
        };
    }

    _scheduleStreamRender() {
        if (this.streamRenderSource) {
            return;
        }
        this.streamRenderSource = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            33,
            Lang.bind(this, function() {
                this.streamRenderSource = 0;
                this._updateActiveMessageBubble();
                return GLib.SOURCE_REMOVE;
            })
        );
    }

    _cancelStreamRender() {
        if (this.streamRenderSource) {
            GLib.source_remove(this.streamRenderSource);
            this.streamRenderSource = 0;
        }
    }

    _flushStreamRender() {
        this._cancelStreamRender();
        this._updateActiveMessageBubble();
    }

    _updateActiveMessageBubble() {
        if (this.activeMessageBubble && this.activeMessage) {
            this.activeMessageBubble.set_text(this.activeMessage.content || "...");
        }
    }

    _stopGeneration() {
        this._cancelActiveRequest();
        if (this.activeMessage && !this.activeMessage.content) {
            this.activeMessage.content = "Stopped.";
        }
        this._setGenerating(false);
        this._flushStreamRender();
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
        this._cancelStreamRender();
        this.messages = [];
        this.activeMessage = null;
        this._setGenerating(false);
        this._renderMessages();
    }

    _openFullChat() {
        let messages = this.messages.filter(function(message) {
            return !!message.content;
        }).map(function(message) {
            return { role: message.role, content: message.content };
        });

        if (!messages.length) {
            this._openUrl(this.serverUrl);
            return;
        }

        let payload = {
            model: this.model || this.modelName || DEFAULT_MODEL,
            messages: messages
        };
        this._request("POST", this.serverUrl + "/api/handoffs", JSON.stringify(payload), Lang.bind(this, function(status, body) {
            if (status >= 200 && status < 300) {
                try {
                    let data = JSON.parse(body);
                    if (data.path) {
                        this._openUrl(this.serverUrl + data.path);
                        return;
                    }
                } catch (e) {
                    // Fall through and open the web UI without a handoff.
                }
            }
            this.statusLabel.set_text("Unable to transfer chat; opened full chat without history");
            this._openUrl(this.serverUrl);
        }));
    }

    _openUrl(url) {
        Util.spawn(["xdg-open", url]);
    }

    _setGenerating(isGenerating) {
        this.isGenerating = isGenerating;
        this.sendButton.reactive = !isGenerating;
        this.changeModelButton.reactive = !isGenerating;
        this.stopButton.visible = isGenerating;
    }

    _renderMessages() {
        this.thread.destroy_all_children();
        this.activeMessageBubble = null;

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
        if (message === this.activeMessage) {
            this.activeMessageBubble = bubble;
        }
        item.add_actor(bubble);

        return item;
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    if (!AppletStream) {
        AppletStream = imports.applets[metadata.uuid].appletStream;
    }
    return new LocalMistralChatApplet(metadata, orientation, panelHeight, instanceId);
}
