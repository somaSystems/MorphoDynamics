import numpy as np
from skimage.external.tifffile import TiffWriter, imsave  # , imread  # , imsave
from skimage.segmentation import find_boundaries
from scipy.interpolate import splev
from matplotlib.backends.backend_pdf import PdfPages
from Settings import Struct
from FigureHelper import FigureHelper
from Segmentation import segment
from DisplacementEstimation import fit_spline, map_contours, map_contours2, rasterize_curve, compute_length, \
    compute_area, find_origin, show_edge_scatter  # , show_edge_scatter
from Windowing import create_windows, extract_signals, label_windows, show_windows
# from SignalExtraction import showSignals
import matplotlib.pyplot as plt


def analyze_morphodynamics(data, param):
    # Figures and other artifacts
    if param.showWindows:
        pp = PdfPages(param.resultdir + 'Windows.pdf')
        tw_win = TiffWriter(param.resultdir + 'Windows.tif')

    # Structures that will be saved to disk
    res = Struct()
    res.spline = []
    res.param0 = []
    res.param = []
    res.displacement = np.zeros((param.I, data.K - 1))  # Projection of the displacement vectors
    res.mean = np.zeros((len(data.signalfile), param.J, param.I, data.K))  # Signals from the outer sampling windows
    res.var = np.zeros((len(data.signalfile), param.J, param.I, data.K))  # Signals from the outer sampling windows
    res.length = np.zeros((data.K,))
    res.area = np.zeros((data.K,))
    res.orig = np.zeros((data.K,))

    # from skimage.external.tifffile import imread
    # mask = imread(param.resultdir + '../Mask.tif')

    # Main loop on frames
    # deltat = 0
    tw_seg = TiffWriter(param.resultdir + 'Segmentation.tif')
    # tw_win = TiffWriter(param.resultdir + 'Windows.tif')
    for k in range(0, data.K):
        print(k)
        x = data.load_frame_morpho(k)  # Input image

        if hasattr(param, 'Tfun'):
            c = segment(x, param.sigma, param.Tfun(k), tw_seg)  # Discrete cell contour
        else:
            # c = segment(x, param.sigma, param.T, tw_seg, mask)  # Discrete cell contour
            c = segment(x, param.sigma, param.T, tw_seg)  # Discrete cell contour
        s = fit_spline(c, param.lambda_)  # Smoothed spline curve following the contour
        res.length[k] = compute_length(s)  # Length of the contour
        res.area[k] = compute_area(s)  # Area delimited by the contour
        if 0 < k:
            # t0 = deltat + 0.5 / param.I + np.linspace(0, 1, param.I, endpoint=False)  # Parameters of the startpoints of the displacement vectors
            # # t = map_contours(s0, s, t0)  # Parameters of the endpoints of the displacement vectors
            # t = map_contours2(s0, s, t0)  # Parameters of the endpoints of the displacement vectors
            # deltat += t[0] - t0[0]  # Translation of the origin of the spline curve

            res.orig[k] = find_origin(s0, s, res.orig[k-1])
            t0 = res.orig[k-1] + 0.5 / param.I + np.linspace(0, 1, param.I, endpoint=False)  # Parameters of the startpoints of the displacement vectors
            t = res.orig[k] + 0.5 / param.I + np.linspace(0, 1, param.I, endpoint=False)  # Parameters of the startpoints of the displacement vectors
            t = map_contours2(s0, s, t0, t)  # Parameters of the endpoints of the displacement vectors
        # c = rasterize_curve(x.shape, s, deltat)  # Representation of the contour as a grayscale image
        c = rasterize_curve(x.shape, s, res.orig[k])  # Representation of the contour as a grayscale image
        # if k == 3:
        #     imsave('Contour ' + str(0) + '.tif', rasterize_curve(x.shape, s, 0).astype(np.float32))
        #     imsave('Contour ' + str(0.5) + '.tif', rasterize_curve(x.shape, s, 0.25).astype(np.float32))
        #     quit()
        w = create_windows(c, param.I, param.J)  # Binary masks representing the sampling windows
        for m in range(len(data.signalfile)):
            res.mean[m, :, :, k], res.var[m, :, :, k] = extract_signals(data.load_frame_signal(m, k), w)  # Signals extracted from various imaging channels

        # Compute projection of displacement vectors onto normal of contour
        if 0 < k:
            u = np.asarray(splev(np.mod(t0, 1), s0, der=1))  # Get a vector that is tangent to the contour
            u = np.asarray([u[1], -u[0]]) / np.linalg.norm(u, axis=0)  # Derive an orthogonal vector with unit norm
            res.displacement[:, k - 1] = np.sum((np.asarray(splev(np.mod(t, 1), s)) - np.asarray(splev(np.mod(t0, 1), s0))) * u, axis=0)  # Compute scalar product with displacement vector

        # Artifact generation
        if param.showWindows:
            if 0 < k:
                plt.figure(figsize=(12, 9))
                plt.gca().set_title('Frame ' + str(k-1))
                plt.tight_layout()
                b0 = find_boundaries(label_windows(w0))
                show_windows(w0, b0)  # Show window boundaries and their indices; for a specific window, use: w0[0, 0].astype(dtype=np.uint8)
                show_edge_scatter(s0, s, t0, t, res.displacement[:, k - 1])  # Show edge structures (spline curves, displacement vectors)
                pp.savefig()
                tw_win.save(255 * b0.astype(np.uint8), compress=6)
                plt.close()
            # imsave(param.resultdir + 'Tiles.tif', 255 * np.asarray(w), compress=6)

        # Keep variable for the next iteration
        s0 = s
        w0 = w

        # Save variables for archival
        res.spline.append(s)
        if 0 < k:
            res.param0.append(t0)
            res.param.append(t)

    # Close windows figure
    tw_seg.close()
    if param.showWindows:
        pp.close()
        tw_win.close()

    return res
