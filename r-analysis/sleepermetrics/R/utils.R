# Internal helpers and constants ------------------------------------------

# Canonical offensive position ordering used throughout.
.sl_positions <- c("QB", "RB", "WR", "TE", "K", "DEF")

# Default position fill colours.
.sl_pos_colors <- c(QB = "#d62728", RB = "#2ca02c", WR = "#1f77b4",
                    TE = "#ff7f0e", K = "#9467bd", DEF = "#8c564b")

# Add any missing expected columns as NA so later selects/renames are
# schema-agnostic (older Sleeper seasons carry fewer fields).
ensure_cols <- function(df, cols) {
  miss <- setdiff(cols, names(df))
  if (length(miss)) df[miss] <- NA
  df
}

# A distinct colour per manager name, stable for a given set of names.
#' Build a stable manager colour palette
#'
#' @param names_vec Character vector of manager names.
#' @return A named character vector of hex colours (names = sorted managers).
#' @export
sl_palette <- function(names_vec) {
  nm <- sort(unique(names_vec))
  stats::setNames(
    grDevices::colorRampPalette(RColorBrewer::brewer.pal(12, "Paired"))(length(nm)),
    nm)
}
