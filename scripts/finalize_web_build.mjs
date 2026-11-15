import { existsSync, unlinkSync } from "node:fs";
import { fileURLToPath } from "node:url";

const plain = fileURLToPath(new URL("../apps/web/dist/research/discovery.json", import.meta.url));
const packed = `${plain}.gz`;
if (!existsSync(packed)) throw new Error("Compressed historical research record is missing from the build");
if (existsSync(plain)) unlinkSync(plain);
console.log("Static build retains the lossless compressed historical record");
