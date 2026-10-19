import { useState, type DragEvent, type FormEvent } from "react";

import { checkFile } from "../api";
import type { ContractType } from "../types";

const CONTRACT_TYPES: { value: ContractType | ""; label: string }[] = [
  { value: "", label: "Not specified" },
  { value: "service", label: "Service agreement" },
  { value: "lease", label: "Lease agreement" },
];

interface Props {
  error?: string;
  onSubmit: (file: File, contractType: ContractType | "") => void;
}

export function UploadPanel({ error, onSubmit }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [contractType, setContractType] = useState<ContractType | "">("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function choose(candidate: File | undefined) {
    if (!candidate) return;
    const problem = checkFile(candidate);
    setFileError(problem);
    setFile(problem ? null : candidate);
  }

  function drop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0]);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (file) onSubmit(file, contractType);
  }

  return (
    <form className="upload" onSubmit={submit}>
      <h2 className="upload-title">See each risk in a contract next to the case law on it</h2>
      <p className="lede">
        Every clause is checked for legal risk. For each risk, court and authority decisions are
        searched live and set beside the clause with the reasoning that applies.
      </p>

      <label
        className={`sheet dropzone${dragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <input
          type="file"
          accept=".pdf,.docx"
          aria-label="Choose contract file"
          className="visually-hidden"
          onChange={(event) => choose(event.target.files?.[0])}
        />
        {file ? (
          <>
            <span className="dropzone-title">{file.name}</span>
            <span className="dropzone-hint">Click or drop to choose a different file.</span>
          </>
        ) : (
          <>
            <span className="dropzone-title">Drop the contract here</span>
            <span className="dropzone-hint">or click to choose a file. PDF or DOCX, up to 10 MB.</span>
          </>
        )}
      </label>

      {(fileError || error) && (
        <p className="alert" role="alert">
          {fileError ?? error}
        </p>
      )}

      <fieldset className="contract-type">
        <legend>Contract type</legend>
        {CONTRACT_TYPES.map((option) => (
          <label key={option.value} className="choice">
            <input
              type="radio"
              name="contract-type"
              value={option.value}
              checked={contractType === option.value}
              onChange={() => setContractType(option.value)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>

      <button type="submit" className="button-primary" disabled={!file}>
        Analyze contract
      </button>
      <p className="fineprint">
        Two sample contracts are in the project's <code>samples</code> folder.
      </p>
    </form>
  );
}
