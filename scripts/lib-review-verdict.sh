#!/usr/bin/env bash

has_usable_verdict() {
  local output_file="$1"

  awk '
    function normalize(line, normalized) {
      normalized = tolower(line)
      sub(/^[[:space:]]+/, "", normalized)
      sub(/[[:space:]]+$/, "", normalized)
      sub(/[[:space:]]*[:.-]+$/, "", normalized)
      return normalized
    }
    function valid_verdict(value) {
      return value == "approve" || value == "approve_with_notes" || value == "request_changes"
    }
    BEGIN { in_verdict = 0 }
    tolower($0) ~ /^#+[[:space:]]+verdict[[:space:]:.-]*$/ { in_verdict = 1; next }
    in_verdict && /^#+[[:space:]]+/ { exit }
    in_verdict && /^[[:space:]]*$/ { next }
    in_verdict {
      if ($0 ~ /^[[:space:]]*([-*+]|\(?[0-9]+[.)])([[:space:]]|$)/) {
        bullet = $0
        sub(/^[[:space:]]*([-*+]|\(?[0-9]+[.)])[[:space:]]+/, "", bullet)
        bullet = normalize(bullet)
        if (valid_verdict(bullet)) {
          bullet_count += 1
          bullet_verdict = bullet
        }
        next
      }
      verdict = normalize($0)
      if (valid_verdict(verdict)) {
        found = 1
        exit
      }
    }
    END { exit (found || (bullet_count == 1 && bullet_verdict != "")) ? 0 : 1 }
  ' "${output_file}"
}
