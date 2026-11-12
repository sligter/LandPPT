// Keep the creation forms aligned with FileProcessor's supported_formats.
export const sourceExtensions = ['pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'jpg', 'jpeg', 'png'];
export function contentSource(files: number, urls: number): 'manual' | 'file' | 'url' | 'mixed' {
  return files ? urls ? 'mixed' : 'file' : urls ? 'url' : 'manual';
}
