export async function readStream(body, onToken) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processRecord = (record) => {
    if (!record.trim()) return;
    const data = JSON.parse(record);
    if (data.error) throw new Error(data.error);
    if (data.message?.content) onToken(data.message.content);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      processRecord(buffer);
      return;
    }
    buffer += decoder.decode(value, { stream: true });
    const records = buffer.split("\n");
    buffer = records.pop() || "";
    for (const record of records) processRecord(record);
  }
}
