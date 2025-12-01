from typing import IO, Iterator, Tuple, Union

def parse_fasta(source: Union[str, IO[str]]) -> Iterator[Tuple[str, str]]:
    """
    Parses a FASTA file and yields header-sequence pairs.

    This function reads from a file path or a file-like object and
    iterates through the records. It handles multi-line sequences by
    joining them into a single string.

    Args:
        source: A file path (str) or a file-like object (e.g., open file handle)
                containing FASTA formatted data.

    Yields:
        A tuple containing the header (string, without the leading '>') and
        the corresponding sequence (string).

    Raises:
        FileNotFoundError: If the source is a path and the file does not exist.
        IOError: If there's an issue reading the file.
    """
    if isinstance(source, str):
        with open(source, 'r') as f:
            yield from _parse_fasta_stream(f)
    else:
        yield from _parse_fasta_stream(source)

def _parse_fasta_stream(stream: IO[str]) -> Iterator[Tuple[str, str]]:
    """Helper function to parse a file stream."""
    header = None
    sequence_parts = []

    for line in stream:
        line = line.strip()
        if not line:
            continue

        if line.startswith('>'):
            if header is not None:
                yield header, "".join(sequence_parts)
            header = line[1:].strip()
            sequence_parts = []
        elif header is not None:
            sequence_parts.append(line)

    # Yield the last record in the file
    if header is not None:
        yield header, "".join(sequence_parts)
