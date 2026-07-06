var NdjsonStreamParser = class NdjsonStreamParser {
    constructor(onContent) {
        this.buffer = "";
        this.onContent = onContent;
    }

    push(chunk) {
        this.buffer += chunk;
        let records = this.buffer.split("\n");
        this.buffer = records.pop() || "";
        for (let i = 0; i < records.length; i++) {
            this._process(records[i]);
        }
    }

    finish() {
        this._process(this.buffer);
        this.buffer = "";
    }

    _process(record) {
        if (!record.trim()) {
            return;
        }
        let data;
        try {
            data = JSON.parse(record);
        } catch (error) {
            throw new Error("Invalid streaming response");
        }
        if (data.error) {
            throw new Error(data.error);
        }
        if (data.message && data.message.content) {
            this.onContent(data.message.content);
        }
    }
};
