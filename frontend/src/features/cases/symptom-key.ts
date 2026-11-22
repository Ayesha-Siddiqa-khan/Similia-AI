// A stable id for cards created in this browser session (saved cards already have a server id).
// Used only to remember which card is open; never sent to the server.
let counter = 0;
export const newKey = (): string => `k${Date.now().toString(36)}${(counter++).toString(36)}`;
