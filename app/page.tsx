"use client";

import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

type AppState = "idle" | "uploading" | "analyzing" | "done" | "error";

interface DocumentBlock {
  type: "paragraph" | "bullet" | "numbered" | "equation" | "diagram";
  text: string;
  indentLevel: number;
  isBold: boolean;
  isItalic: boolean;
}

interface DocumentSection {
  heading: string;
  headingLevel: number;
  headingColor: "red" | "black";
  content: DocumentBlock[];
}

interface AnalysisResult {
  title: string;
  layout: "single_column" | "two_column";
  sections: DocumentSection[];
}

interface SelectedImage {
  dataUrl: string;
  name: string;
  size: number;
  type: string;
}

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_CLIENT_BYTES = 10 * 1024 * 1024;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("read_failed"));
    };
    reader.onerror = () => reject(new Error("read_failed"));
    reader.readAsDataURL(file);
  });
}

function parseRemaining(header: string | null, fallback: number): number {
  if (!header) return fallback;
  const parsed = Number.parseInt(header, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

async function extractErrorMessage(response: Response, fallback: string): Promise<string> {
  if (response.status === 429) return "Too many requests. Please wait a moment.";
  if (response.status === 404) {
    return "API endpoint not found (404). If running locally, start the backend with `vercel dev` instead of `npm run dev`.";
  }
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      const data = (await response.json()) as { error?: string };
      if (data?.error && typeof data.error === "string") return data.error;
    } catch {
      // fall through to fallback
    }
  } else {
    try {
      const text = await response.text();
      if (text && text.length < 200) return `${fallback} (HTTP ${response.status}: ${text.trim()})`;
    } catch {
      // fall through
    }
  }
  return `${fallback} (HTTP ${response.status})`;
}

function layoutLabel(layout: AnalysisResult["layout"]): string {
  return layout === "two_column" ? "Two Column" : "Single Column";
}

function sectionColorHex(section: DocumentSection): string {
  return section.headingColor === "red" ? "#c8451a" : "#0a0a0f";
}

function totalBlocks(analysis: AnalysisResult): number {
  return analysis.sections.reduce((sum, section) => sum + section.content.length, 0);
}

export default function HomePage() {
  const [appState, setAppState] = useState<AppState>("idle");
  const [image, setImage] = useState<SelectedImage | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [downloading, setDownloading] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);

  const defaultRemaining = useMemo<number>(() => {
    const envValue = process.env.NEXT_PUBLIC_RATE_LIMIT_MAX;
    if (!envValue) return 10;
    const parsed = Number.parseInt(envValue, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 10;
  }, []);

  const [remaining, setRemaining] = useState<number>(defaultRemaining);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setRemaining(defaultRemaining);
  }, [defaultRemaining]);

  const resetAll = useCallback(() => {
    setImage(null);
    setAnalysis(null);
    setErrorMessage("");
    setAppState("idle");
    setDownloading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const file = files[0];
      if (!file) return;

      if (!ACCEPTED_TYPES.includes(file.type)) {
        setErrorMessage("Unsupported file type. Use JPG, PNG, or WEBP.");
        setAppState("error");
        return;
      }
      if (file.size > MAX_CLIENT_BYTES) {
        setErrorMessage("Image exceeds the 10MB limit.");
        setAppState("error");
        return;
      }

      setAppState("uploading");
      setErrorMessage("");
      try {
        const dataUrl = await readFileAsDataUrl(file);
        setImage({ dataUrl, name: file.name, size: file.size, type: file.type });
        setAnalysis(null);
        setAppState("idle");
      } catch {
        setErrorMessage("Could not read the selected file.");
        setAppState("error");
      }
    },
    []
  );

  const handleInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      void handleFiles(event.target.files);
    },
    [handleFiles]
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      void handleFiles(event.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  }, []);

  const openFileDialog = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const analyze = useCallback(async () => {
    if (!image) return;
    setAppState("analyzing");
    setErrorMessage("");
    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ imageDataUrl: image.dataUrl })
      });
      setRemaining(parseRemaining(response.headers.get("X-RateLimit-Remaining"), remaining));
      if (!response.ok) {
        const message = await extractErrorMessage(response, "Analysis failed.");
        console.error("scriptorium.analyze.failed", { status: response.status, message });
        setErrorMessage(message);
        setAppState("error");
        return;
      }
      const data = (await response.json()) as { analysis?: AnalysisResult };
      if (!data.analysis || !Array.isArray(data.analysis.sections)) {
        setErrorMessage("Received an unexpected response.");
        setAppState("error");
        return;
      }
      setAnalysis(data.analysis);
      setAppState("done");
    } catch {
      setErrorMessage("Network error. Please check your connection and try again.");
      setAppState("error");
    }
  }, [image, remaining]);

  const download = useCallback(async () => {
    if (!analysis || !image) return;
    setDownloading(true);
    setErrorMessage("");
    try {
      const base = image.name.replace(/\.[^.]+$/, "") || "converted_document";
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis, filename: base })
      });
      setRemaining(parseRemaining(response.headers.get("X-RateLimit-Remaining"), remaining));
      if (!response.ok) {
        const message = await extractErrorMessage(response, "Conversion failed.");
        console.error("scriptorium.convert.failed", { status: response.status, message });
        setErrorMessage(message);
        setAppState("error");
        return;
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match && match[1] ? match[1] : `${base}.docx`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch {
      setErrorMessage("Network error while downloading. Please try again.");
      setAppState("error");
    } finally {
      setDownloading(false);
    }
  }, [analysis, image, remaining]);

  const analyzeAgain = useCallback(() => {
    setAnalysis(null);
    setErrorMessage("");
    setAppState("idle");
  }, []);

  const renderHeader = () => (
    <header className="w-full border-b border-paper-line">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-baseline gap-4">
          <span className="font-display text-[28px] leading-none">Scriptorium</span>
          <span className="text-[11px] uppercase tracking-[0.16em] text-muted-ink">
            Image to Word Converter
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-[11px] text-muted-ink">{remaining} req remaining</span>
        </div>
      </div>
    </header>
  );

  const renderDropZone = () => (
    <div
      className={`drop-zone ${isDragging ? "is-active" : ""} flex flex-col items-center justify-center rounded-sm bg-surface-paper px-10 py-[60px] text-center`}
      onClick={openFileDialog}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openFileDialog();
        }
      }}
    >
      <span className="text-[40px] leading-none text-muted-ink" aria-hidden="true">
        &#128196;
      </span>
      <p className="font-display mt-6 text-[24px] leading-tight">Drop your image here</p>
      <p className="mt-2 text-[12px] text-muted-ink">or click to browse</p>
      <p className="mt-1 text-[11px] text-muted-ink">JPG, PNG, WEBP up to 10MB</p>
    </div>
  );

  const renderImageCard = () => {
    if (!image) return null;
    const showOverlay = appState === "analyzing" || appState === "uploading";
    return (
      <div className="relative overflow-hidden rounded-sm border border-paper-line bg-surface-paper">
        <div className="flex items-center justify-center p-4" style={{ maxHeight: 320 }}>
          <img
            src={image.dataUrl}
            alt={image.name}
            style={{ maxHeight: 300, objectFit: "contain", width: "100%" }}
          />
        </div>
        <div className="flex items-center justify-between border-t border-paper-line px-4 py-2">
          <span className="truncate text-[11px] text-muted-ink" title={image.name}>
            {image.name}
          </span>
          <span className="text-[11px] text-muted-ink">{formatFileSize(image.size)}</span>
        </div>
        {showOverlay ? (
          <div className="overlay">
            <div className="spinner" />
            <p className="text-[12px] text-muted-ink">
              {appState === "analyzing" ? "Analyzing with AI Vision..." : "Reading image..."}
            </p>
          </div>
        ) : null}
      </div>
    );
  };

  const renderIdle = () => (
    <div className="mx-auto flex min-h-[calc(100vh-88px)] max-w-2xl flex-col items-center justify-center gap-5 px-6 py-12">
      {!image ? renderDropZone() : renderImageCard()}
      {image ? (
        <div className="flex w-full flex-col items-center gap-3">
          <button
            type="button"
            className="btn-primary w-full"
            onClick={analyze}
            disabled={appState === "uploading"}
          >
            Analyze Document
          </button>
          <button type="button" className="btn-link" onClick={resetAll}>
            Clear
          </button>
        </div>
      ) : null}
    </div>
  );

  const renderAnalyzing = () => (
    <div className="mx-auto flex min-h-[calc(100vh-88px)] max-w-2xl flex-col items-center justify-center gap-5 px-6 py-12">
      {renderImageCard()}
      <button type="button" className="btn-primary w-full" disabled>
        Analyzing...
      </button>
    </div>
  );

  const renderDone = () => {
    if (!analysis || !image) return null;
    return (
      <div className="mx-auto grid min-h-[calc(100vh-88px)] max-w-6xl grid-cols-1 gap-8 px-6 py-10 lg:grid-cols-[1fr_1fr]">
        <div className="flex flex-col gap-4">{renderImageCard()}</div>
        <div className="results-panel rounded-sm p-6">
          <div className="flex items-center justify-between">
            <span className="badge">{layoutLabel(analysis.layout)}</span>
            <span className="text-[11px] text-muted-ink">
              {analysis.sections.length} sections · {totalBlocks(analysis)} blocks
            </span>
          </div>
          {analysis.title ? (
            <h2 className="font-display mt-4 text-[20px] leading-tight">{analysis.title}</h2>
          ) : (
            <p className="mt-4 text-[12px] text-muted-ink">No title detected</p>
          )}
          <div className="mt-5 space-y-2 border-t border-paper-line pt-4">
            <p className="text-[11px] uppercase tracking-[0.12em] text-muted-ink">Sections</p>
            <ul className="space-y-2">
              {analysis.sections.map((section, index) => (
                <li
                  key={`${index}-${section.heading}`}
                  className="flex items-center gap-3 text-[12px]"
                >
                  <span
                    className="color-square"
                    style={{ backgroundColor: sectionColorHex(section) }}
                    aria-hidden="true"
                  />
                  <span className="text-muted-ink">H{section.headingLevel}</span>
                  <span className="truncate">
                    {section.heading || <em className="text-muted-ink">untitled section</em>}
                  </span>
                  <span className="ml-auto text-[11px] text-muted-ink">
                    {section.content.length}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-6 flex flex-col gap-3">
            <button
              type="button"
              className="btn-primary flex w-full items-center justify-center gap-3"
              onClick={download}
              disabled={downloading}
            >
              {downloading ? <span className="spinner spinner-sm" aria-hidden="true" /> : null}
              {downloading ? "Preparing..." : "Download .docx"}
            </button>
            <button type="button" className="btn-ghost w-full" onClick={analyzeAgain}>
              Analyze Again
            </button>
            <button type="button" className="btn-link" onClick={resetAll}>
              Upload New Image
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderError = () => (
    <div className="mx-auto flex min-h-[calc(100vh-88px)] max-w-2xl flex-col items-center justify-center gap-5 px-6 py-12">
      {image ? renderImageCard() : null}
      <div className="error-box w-full rounded-sm p-4 text-[12px]">
        {errorMessage || "Something went wrong."}
      </div>
      <div className="flex w-full flex-col items-center gap-3">
        <button
          type="button"
          className="btn-primary w-full"
          onClick={image && analysis ? download : image ? analyze : openFileDialog}
        >
          Try Again
        </button>
        <button type="button" className="btn-link" onClick={resetAll}>
          Upload New Image
        </button>
      </div>
    </div>
  );

  const renderBody = () => {
    switch (appState) {
      case "analyzing":
        return renderAnalyzing();
      case "done":
        return renderDone();
      case "error":
        return renderError();
      case "uploading":
      case "idle":
      default:
        return renderIdle();
    }
  };

  return (
    <main className="min-h-screen">
      {renderHeader()}
      {renderBody()}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        className="hidden"
        onChange={handleInputChange}
      />
    </main>
  );
}
