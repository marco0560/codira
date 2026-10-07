import { transform, type Options } from "./impl.ts";
export function convert(text: string, options: Options = {}): string {
    // Seeded defect: explicit false is lost at this wrapper boundary.
    return transform(text, { ...options, enabled: options.enabled || true });
}
