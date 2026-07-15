# Player portraits for the charts (mirrors python/sleepermetrics/headshots.py) --
#
# Sleeper hosts a headshot per player id, and a logo per team -- a team defense
# has no face, so it gets its team's logo instead.
#
# Everything here is best-effort by design. Chart rendering must never depend on
# the network being up, so a fetch that fails (offline, 403 for a player with no
# photo, slow CDN) returns NULL and the caller falls back to a plain text label.
# Failures are cached too: a chart with 20 players must not re-attempt 20 dead
# downloads on every redraw.
#
# Set SLEEPERMETRICS_NO_IMAGES=1 to turn portraits off entirely (tests do this,
# so the suite stays network-free).

SL_PLAYER_CDN <- "https://sleepercdn.com/content/nfl/players"
SL_TEAM_CDN   <- "https://sleepercdn.com/images/team_logos/nfl"

# Ids known to have no image -- never retried.
.sl_shot_miss <- new.env(parent = emptyenv())

.sl_cache_dir <- function() {
  # NB on Windows R expands "~" to Documents/, not the user's home -- which would
  # put the R cache somewhere the Python instance never looks. Prefer the real
  # home so both instances share one downloaded set of portraits.
  home <- Sys.getenv("USERPROFILE", unset = "")
  if (!nzchar(home)) home <- Sys.getenv("HOME", unset = path.expand("~"))
  root <- Sys.getenv("SLEEPERMETRICS_CACHE",
                     file.path(home, ".cache", "sleepermetrics"))
  file.path(root, "headshots")
}

.sl_images_off <- function() {
  !Sys.getenv("SLEEPERMETRICS_NO_IMAGES", "") %in% c("", "0")
}

#' Portrait url for a player (or team logo for a team defense)
#' @param player_id Sleeper player id.
#' @param position Player position; `"DEF"` selects the team logo.
#' @return A url string.
#' @export
sl_headshot_url <- function(player_id, position = NULL) {
  pid <- as.character(player_id)
  is_def <- (!is.null(position) && identical(position, "DEF")) ||
    (grepl("^[A-Za-z]+$", pid) && nchar(pid) <= 4)
  if (is_def) paste0(SL_TEAM_CDN, "/", tolower(pid), ".png")
  else paste0(SL_PLAYER_CDN, "/", pid, ".jpg")
}

#' Local path to a player's portrait, downloading it once
#'
#' @param player_id Sleeper player id.
#' @param position Player position (`"DEF"` -> team logo).
#' @return Path to a cached image, or `NULL` when there is no image / no network.
#' @export
sl_headshot <- function(player_id, position = NULL) {
  if (is.null(player_id) || is.na(player_id) || .sl_images_off()) return(NULL)
  pid <- as.character(player_id)
  if (!is.null(.sl_shot_miss[[pid]])) return(NULL)

  url <- sl_headshot_url(pid, position)
  dir <- .sl_cache_dir()
  dest <- file.path(dir, paste0(pid, tools::file_ext(url) |> (\(e) paste0(".", e))()))
  if (file.exists(dest)) return(dest)

  ok <- tryCatch({
    if (!dir.exists(dir)) dir.create(dir, recursive = TRUE, showWarnings = FALSE)
    h <- curl::new_handle(timeout = 6L)
    tmp <- tempfile()
    resp <- curl::curl_fetch_disk(url, tmp, handle = h)
    # A player with no photo answers 403 with an HTML error page, not a 404, so
    # status alone is not enough -- insist on actually being handed an image.
    ctype <- resp$type %||% ""
    if (resp$status_code == 200 && grepl("^image/", ctype)) {
      file.rename(tmp, dest); TRUE
    } else FALSE
  }, error = function(e) FALSE)         # offline, timeout, whatever

  if (!isTRUE(ok)) {
    .sl_shot_miss[[pid]] <- TRUE        # degrade to text, and stop trying
    return(NULL)
  }
  dest
}

#' A player's portrait as a grid raster, ready to draw on a plot
#'
#' Cropped to a square and rounded off, so a portrait sits in the chart as a
#' circular token rather than a photo with a hard rectangular edge.
#'
#' @param player_id Sleeper player id.
#' @param position Player position (`"DEF"` -> team logo).
#' @param size_mm Drawn size. Fixed in mm rather than data units so the portrait
#'   stays a circle instead of being stretched to whatever box it lands in.
#' @return A `rasterGrob`, or `NULL` when there is no image.
#' @export
sl_headshot_grob <- function(player_id, position = NULL, size_mm = 6.5) {
  path <- sl_headshot(player_id, position)
  if (is.null(path)) return(NULL)
  tryCatch({
    # Sniff the magic bytes rather than trust the extension: Sleeper happily
    # serves a PNG from a .jpg url, and readJPEG() then dies on it.
    magic <- readBin(path, "raw", 2L)
    img <- if (identical(as.integer(magic), c(0x89L, 0x50L))) {
      png::readPNG(path)
    } else {
      jpeg::readJPEG(path)
    }
    if (length(dim(img)) == 2L) img <- array(rep(img, 3), c(dim(img), 3))  # greyscale
    n <- min(dim(img)[1:2])                       # centre-crop to a square
    r0 <- floor((dim(img)[1] - n) / 2) + 1
    c0 <- floor((dim(img)[2] - n) / 2) + 1
    img <- img[r0:(r0 + n - 1), c0:(c0 + n - 1), , drop = FALSE]

    # A team logo is a PNG with its own transparency; keep it, or the logo comes
    # out sitting on a black square.
    own <- if (dim(img)[3] >= 4L) img[, , 4] else matrix(1, n, n)

    # Round it off: alpha 0 outside the inscribed circle.
    ax <- matrix(rep(seq_len(n), each = n), n, n)
    ay <- matrix(rep(seq_len(n), times = n), n, n)
    ctr <- (n + 1) / 2
    inside <- ((ax - ctr)^2 + (ay - ctr)^2) <= (n / 2)^2
    alpha <- own * ifelse(inside, 1, 0)
    rgb <- grDevices::rgb(img[, , 1], img[, , 2], img[, , 3], alpha = alpha)
    grid::rasterGrob(matrix(rgb, n, n), interpolate = TRUE,
                     width = grid::unit(size_mm, "mm"),
                     height = grid::unit(size_mm, "mm"))
  }, error = function(e) NULL)
}

# Portrait layers for a horizontal bar chart: one raster per row, hung just left
# of x = 0 (outside the panel -- the caller must set coord clip = "off").
#
# `d` needs player_id, position, and `yfac` (the factor the y axis is built on).
# Rows with no portrait simply get no layer and keep their text label.
.sl_portraits <- function(d, xspan, size_mm = 6.5, at = -0.045) {
  lays <- list()
  for (i in seq_len(nrow(d))) {
    g <- sl_headshot_grob(d$player_id[i], as.character(d$position[i]), size_mm)
    if (is.null(g)) next
    y <- as.integer(d$yfac[i])
    x <- xspan * at
    # Equal xmin/xmax and ymin/ymax centre the grob at that point and let it keep
    # its own (fixed, square) size rather than being stretched to a box.
    lays[[length(lays) + 1L]] <- ggplot2::annotation_custom(
      g, xmin = x, xmax = x, ymin = y, ymax = y)
  }
  lays
}

#' Forget cached portrait misses (and optionally the downloaded files)
#' @param disk Also delete the cached image files.
#' @return `TRUE`, invisibly.
#' @export
sl_clear_headshots <- function(disk = FALSE) {
  rm(list = ls(envir = .sl_shot_miss), envir = .sl_shot_miss)
  if (disk && dir.exists(.sl_cache_dir())) {
    unlink(list.files(.sl_cache_dir(), full.names = TRUE))
  }
  invisible(TRUE)
}
