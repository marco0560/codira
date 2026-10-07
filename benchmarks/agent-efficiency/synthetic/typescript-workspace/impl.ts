export type Options = { enabled?: boolean; mode?: "upper" | "lower" };
export function transform(text: string, options: Options = {}): string {
    if (options.enabled === false) return text;
    return options.mode === "lower" ? text.toLowerCase() : text.toUpperCase();
}
