import { useState, type DragEvent, type FormEvent } from "react";

import { checkFile } from "../api";
import type { ContractType } from "../types";

const CONTRACT_TYPES: { value: ContractType | ""; label: string }[] = [
  { value: "", label: "Belirtmeyeceğim" },
  { value: "service", label: "Hizmet sözleşmesi" },
  { value: "lease", label: "Kira sözleşmesi" },
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
      <p className="lede">
        Sözleşmeyi yükleyin; her maddeyi risk açısından inceleyip ilgili Yargıtay, Danıştay ve
        KVKK kararlarıyla birlikte gösterelim.
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
          aria-label="Sözleşme dosyası seç"
          className="visually-hidden"
          onChange={(event) => choose(event.target.files?.[0])}
        />
        {file ? (
          <>
            <span className="dropzone-title">{file.name}</span>
            <span className="dropzone-hint">Başka bir dosya seçmek için tıklayın ya da sürükleyin.</span>
          </>
        ) : (
          <>
            <span className="dropzone-title">Sözleşmeyi buraya bırakın</span>
            <span className="dropzone-hint">ya da tıklayıp dosya seçin. PDF veya DOCX, en fazla 10 MB.</span>
          </>
        )}
      </label>

      {(fileError || error) && (
        <p className="alert" role="alert">
          {fileError ?? error}
        </p>
      )}

      <fieldset className="contract-type">
        <legend>Sözleşme türü</legend>
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
        Analizi başlat
      </button>
      <p className="fineprint">
        Deneme için proje klasöründeki <code>samples</code> dizininde iki örnek sözleşme var.
      </p>
    </form>
  );
}
