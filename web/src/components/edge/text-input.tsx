"use client";

import { useId } from "react";
import { Input } from "@/components/ui/input";

// A labelled text input with an inline error, for typed odds, lines and amounts
export function TextInput({ label, value, onChange, error, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error: string | null;
  placeholder: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>
      <Input
        id={id} value={value} placeholder={placeholder} autoComplete="off" spellCheck={false}
        aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && <p id={`${id}-error`} className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
