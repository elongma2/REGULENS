import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

interface ProductContextComboboxProps {
  value: string;
  options: string[];
  unresolved: boolean;
  disabled: boolean;
  onSelect: (value: string) => void | Promise<void>;
}

export function ProductContextCombobox({
  value,
  options,
  unresolved,
  disabled,
  onSelect,
}: ProductContextComboboxProps) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);

  const uniqueOptions = useMemo(
    () => [...new Set(options)].sort((left, right) => left.localeCompare(right)),
    [options],
  );
  const filteredOptions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized
      ? uniqueOptions.filter((option) => option.toLocaleLowerCase().includes(normalized))
      : uniqueOptions;
  }, [query, uniqueOptions]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const showUnavailableChoice = !normalizedQuery || "no product context supplied".includes(normalizedQuery);
  const optionOffset = showUnavailableChoice ? 1 : 0;
  const allChoices = [...(showUnavailableChoice ? [""] : []), ...filteredOptions];
  const activeIndex = Math.min(highlighted, Math.max(allChoices.length - 1, 0));

  useEffect(() => {
    if (!open) return;
    searchRef.current?.focus();
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const openList = () => {
    if (disabled) return;
    setQuery("");
    setHighlighted(Math.max(0, uniqueOptions.indexOf(value) + 1));
    setOpen(true);
  };

  const closeList = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const choose = async (nextValue: string) => {
    setOpen(false);
    await onSelect(nextValue);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const displayValue = value || (unresolved ? "Choose a product context" : "No product context supplied");

  return (
    <div className="product-context-combobox" ref={rootRef}>
      <button
        ref={triggerRef}
        className={`field-control product-context-trigger ${unresolved ? "is-unresolved" : ""}`}
        type="button"
        aria-label="Agent Product context"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        disabled={disabled}
        onClick={() => open ? closeList() : openList()}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            openList();
          }
        }}
      >
        <span>{displayValue}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>

      {open && (
        <div className="product-context-popover">
          <label className="product-context-search">
            <Search size={15} aria-hidden="true" />
            <span className="sr-only">Search accepted product contexts</span>
            <input
              ref={searchRef}
              role="combobox"
              aria-label="Search accepted product contexts"
              aria-autocomplete="list"
              aria-controls={listboxId}
              aria-expanded="true"
              aria-activedescendant={allChoices.length ? `${listboxId}-${activeIndex}` : undefined}
              value={query}
              placeholder={`Search ${uniqueOptions.length} accepted contexts`}
              onChange={(event) => { setQuery(event.target.value); setHighlighted(0); }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeList(true);
                } else if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setHighlighted((current) => Math.min(current + 1, allChoices.length - 1));
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setHighlighted((current) => Math.max(current - 1, 0));
                } else if (event.key === "Home") {
                  event.preventDefault();
                  setHighlighted(0);
                } else if (event.key === "End") {
                  event.preventDefault();
                  setHighlighted(allChoices.length - 1);
                } else if (event.key === "Enter") {
                  if (allChoices.length === 0) return;
                  event.preventDefault();
                  void choose(allChoices[activeIndex]);
                }
              }}
            />
          </label>
          <div className="product-context-result-count" aria-live="polite">
            {filteredOptions.length === uniqueOptions.length
              ? `${uniqueOptions.length} accepted contexts`
              : `${filteredOptions.length} of ${uniqueOptions.length} contexts`}
          </div>
          <div id={listboxId} className="product-context-options" role="listbox" aria-label="Accepted product contexts">
            {showUnavailableChoice && (
              <button
                id={`${listboxId}-0`}
                type="button"
                role="option"
                aria-selected={value === ""}
                className={activeIndex === 0 ? "is-highlighted" : ""}
                onMouseEnter={() => setHighlighted(0)}
                onClick={() => void choose("")}
              >
                <span>No product context supplied</span>
                {value === "" && !unresolved && <Check size={15} aria-hidden="true" />}
              </button>
            )}
            {filteredOptions.map((option, index) => {
              const optionIndex = index + optionOffset;
              return (
                <button
                  id={`${listboxId}-${optionIndex}`}
                  type="button"
                  role="option"
                  aria-selected={value === option}
                  className={activeIndex === optionIndex ? "is-highlighted" : ""}
                  key={option}
                  onMouseEnter={() => setHighlighted(optionIndex)}
                  onClick={() => void choose(option)}
                >
                  <span>{option}</span>
                  {value === option && <Check size={15} aria-hidden="true" />}
                </button>
              );
            })}
            {filteredOptions.length === 0 && (
              <p className="product-context-empty">No accepted context matches this search.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
