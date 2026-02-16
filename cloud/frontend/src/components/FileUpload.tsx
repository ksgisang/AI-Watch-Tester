"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";

interface Props {
  onFilesChanged: (files: File[]) => void;
}

const ACCEPT = ".md,.txt,.pdf,.docx";
const MAX_SIZE = 10 * 1024 * 1024; // 10MB

export default function FileUpload({ onFilesChanged }: Props) {
  const t = useTranslations("fileUpload");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList || fileList.length === 0) return;
      setError("");

      const newFiles: File[] = [];
      for (const file of Array.from(fileList)) {
        // Validate extension
        const ext = file.name.split(".").pop()?.toLowerCase();
        if (!["md", "txt", "pdf", "docx"].includes(ext || "")) {
          setError(t("unsupportedFile", { name: file.name }));
          continue;
        }
        // Validate size
        if (file.size > MAX_SIZE) {
          setError(t("fileTooLarge", { name: file.name }));
          continue;
        }
        newFiles.push(file);
      }

      if (newFiles.length > 0) {
        const updated = [...files, ...newFiles];
        setFiles(updated);
        onFilesChanged(updated);
      }
    },
    [files, onFilesChanged, t]
  );

  const removeFile = useCallback(
    (index: number) => {
      const updated = files.filter((_, i) => i !== index);
      setFiles(updated);
      onFilesChanged(updated);
    },
    [files, onFilesChanged]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  return (
    <div className="space-y-2">
      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-3 text-center transition-colors ${
          dragOver
            ? "border-blue-400 bg-blue-50"
            : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-gray-500">
          {t("dropHint")}
        </p>
        <p className="mt-0.5 text-xs text-gray-400">
          {t("formats")}
        </p>
      </div>

      {/* Error */}
      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* Staged files */}
      {files.length > 0 && (
        <div className="space-y-1">
          {files.map((f, i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded bg-gray-50 px-3 py-1.5 text-xs"
            >
              <span className="font-medium text-gray-700">{f.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-gray-400">
                  {(f.size / 1024).toFixed(0)}KB
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  className="text-gray-400 hover:text-red-500"
                >
                  &#10005;
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
