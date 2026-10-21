/**
 * Join conditional class names. Falsy entries are dropped, so the common
 * `condition && "class"` and `count && "class"` idioms both work.
 */
type ClassValue = string | number | bigint | boolean | null | undefined;

export function cn(...parts: ClassValue[]): string {
  return parts.filter((part): part is string => typeof part === "string" && part !== "").join(" ");
}
