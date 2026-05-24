/**
 * 共享 K 线 + 成交量 + KDJ(J) 图表（支持日线 / 周线 / 季线）
 */
(function (global) {
    function parseOhlcRow(row) {
        if (!row || row.length < 4) return null;
        var o, c, l, h;
        if (row.length >= 6) {
            o = parseFloat(row[1]);
            c = parseFloat(row[2]);
            l = parseFloat(row[3]);
            h = parseFloat(row[4]);
        } else {
            o = parseFloat(row[0]);
            c = parseFloat(row[1]);
            l = parseFloat(row[2]);
            h = parseFloat(row[3]);
        }
        if (isNaN(o) || isNaN(c) || isNaN(l) || isNaN(h)) return null;
        if (o <= 0 || c <= 0 || l <= 0 || h <= 0) return null;
        var top = Math.max(o, c);
        var bottom = Math.min(o, c);
        if (l > bottom + 0.001 || h < top - 0.001) return null;
        return [o, c, l, h];
    }

    function toLineData(arr) {
        if (!arr) return [];
        return arr.map(function (v) {
            if (v === null || v === undefined || v === '-' || v === '') return null;
            var n = parseFloat(v);
            return isNaN(n) ? null : n;
        });
    }

    /** 按当前可见区间计算主图 Y 轴，使 K 线尽量占满价格区 */
    function calcPriceYRange(ctx, startPercent, endPercent) {
        var list = ctx.ohlcList;
        var n = list.length;
        if (!n) return null;

        var start = Math.max(0, Math.floor(n * startPercent / 100));
        var end = Math.min(n - 1, Math.max(start, Math.ceil(n * endPercent / 100) - 1));
        var minP = Infinity;
        var maxP = -Infinity;

        for (var i = start; i <= end; i++) {
            var row = list[i];
            if (!row) continue;
            minP = Math.min(minP, row[2], row[0], row[1]);
            maxP = Math.max(maxP, row[3], row[0], row[1]);
        }
        if (!isFinite(minP) || !isFinite(maxP)) return null;

        var overlays = [ctx.ma60, ctx.ma8, ctx.zxShort, ctx.zxDuokong];
        var bandLo = minP * 0.88;
        var bandHi = maxP * 1.12;
        for (var j = start; j <= end; j++) {
            for (var s = 0; s < overlays.length; s++) {
                var arr = overlays[s];
                if (!arr) continue;
                var v = arr[j];
                if (v == null || isNaN(v) || v <= 0) continue;
                if (v >= bandLo && v <= bandHi) {
                    minP = Math.min(minP, v);
                    maxP = Math.max(maxP, v);
                }
            }
        }

        var span = maxP - minP;
        var pad = span > 0 ? span * 0.04 : Math.max(minP * 0.02, 0.01);
        return {
            min: +(minP - pad).toFixed(4),
            max: +(maxP + pad).toFixed(4)
        };
    }

    function getDataZoomPercent(chart) {
        var opt = chart.getOption();
        var dzArr = opt.dataZoom || [];
        var start = 10;
        var end = 100;
        for (var i = 0; i < dzArr.length; i++) {
            var dz = dzArr[i];
            if (dz.xAxisIndex != null && dz.start != null && dz.end != null) {
                start = dz.start;
                end = dz.end;
                break;
            }
        }
        return { start: start, end: end };
    }

    function applyPriceYAxisFit(chart, ctx) {
        var zoom = getDataZoomPercent(chart);
        var range = calcPriceYRange(ctx, zoom.start, zoom.end);
        if (!range) return;
        chart.setOption({
            yAxis: [{ min: range.min, max: range.max, scale: false }]
        });
    }

    function bindPriceAxisAutoFit(chart, chartHolder, ctx) {
        if (chartHolder._saPriceFitHandler) {
            chart.off('datazoom', chartHolder._saPriceFitHandler);
        }
        chartHolder._saPriceFitHandler = function () {
            applyPriceYAxisFit(chart, ctx);
        };
        chart.on('datazoom', chartHolder._saPriceFitHandler);
        applyPriceYAxisFit(chart, ctx);
    }

    /** J < 0 时在 KDJ 子图最底部标红箭头（固定 Y，不压在 J 线上） */
    function calcDailyPctChg(ohlcList) {
        var pct = [];
        for (var i = 0; i < ohlcList.length; i++) {
            if (i === 0) {
                pct.push(null);
                continue;
            }
            var prevClose = ohlcList[i - 1][1];
            var close = ohlcList[i][1];
            if (!prevClose || prevClose === 0) {
                pct.push(null);
                continue;
            }
            pct.push(((close - prevClose) / prevClose) * 100);
        }
        return pct;
    }

    function formatPctChg(v) {
        if (v === null || v === undefined || isNaN(v)) return '—';
        var sign = v > 0 ? '+' : '';
        return sign + v.toFixed(2) + '%';
    }

    function buildJBelowZeroMarkPoints(dates, jLine) {
        var pts = [];
        var minJ = null;
        for (var k = 0; k < jLine.length; k++) {
            var v = jLine[k];
            if (v === null || v === undefined || isNaN(v)) continue;
            if (minJ === null || v < minJ) minJ = v;
        }
        var arrowY = (minJ !== null ? minJ : 0) - 14;
        for (var i = 0; i < jLine.length; i++) {
            var j = jLine[i];
            if (j === null || j === undefined || isNaN(j) || j >= 0) continue;
            pts.push({ coord: [dates[i], arrowY] });
        }
        return pts;
    }

    function buildKlineChartOption(data) {
        var isOamv = data.chart_type === 'oamv';
        var upColor = '#EF232A';
        var downColor = '#00DA3C';
        var kName = data.period_label || '日K';
        var periodName = data.period_name || '日线';
        var volSeriesName = isOamv ? '成交额' : '成交量';
        var rawDates = data.dates || [];
        var rawKlines = data.klines || [];
        var rawVolumes = data.volumes || [];

        var rawMa60 = toLineData(data.tech_datas && data.tech_datas.MA60);
        var rawMa8 = toLineData(data.tech_datas && data.tech_datas.MA8);
        var rawMa120 = toLineData(data.tech_datas && data.tech_datas.MA120);
        if (!rawMa8.length && rawMa120.length) rawMa8 = rawMa120;
        var rawCyc5 = toLineData(data.tech_datas && data.tech_datas.CYC5);
        var rawCyc13 = toLineData(data.tech_datas && data.tech_datas.CYC13);
        var rawZxShort = toLineData(data.tech_datas && data.tech_datas.ZX_SHORT_TREND);
        var rawZxDuokong = toLineData(data.tech_datas && data.tech_datas.ZX_DUOKONG);
        var rawJ = toLineData(data.tech_datas && data.tech_datas.J);

        var dates = [];
        var ohlcList = [];
        var volumeBars = [];
        var ma60 = [];
        var ma8 = [];
        var cyc5 = [];
        var cyc13 = [];
        var zxShort = [];
        var zxDuokong = [];
        var jLine = [];

        for (var i = 0; i < rawKlines.length; i++) {
            var ohlc = parseOhlcRow(rawKlines[i]);
            if (!ohlc) continue;
            dates.push(rawDates[i]);
            ohlcList.push(ohlc);
            var open = ohlc[0];
            var close = ohlc[1];
            volumeBars.push({
                value: rawVolumes[i],
                itemStyle: { color: open >= close ? downColor : upColor }
            });
            ma60.push(i < rawMa60.length ? rawMa60[i] : null);
            ma8.push(i < rawMa8.length ? rawMa8[i] : null);
            cyc5.push(i < rawCyc5.length ? rawCyc5[i] : null);
            cyc13.push(i < rawCyc13.length ? rawCyc13[i] : null);
            zxShort.push(i < rawZxShort.length ? rawZxShort[i] : null);
            zxDuokong.push(i < rawZxDuokong.length ? rawZxDuokong[i] : null);
            jLine.push(i < rawJ.length ? rawJ[i] : null);
        }

        var jBelowZeroArrows = buildJBelowZeroMarkPoints(dates, jLine);
        var dailyPctChg = calcDailyPctChg(ohlcList);

        var klineCtx = isOamv
            ? { ohlcList: ohlcList, ma60: cyc5, ma8: cyc13, zxShort: [], zxDuokong: [] }
            : { ohlcList: ohlcList, ma60: ma60, ma8: ma8, zxShort: zxShort, zxDuokong: zxDuokong };
        var initZoom = { start: 10, end: 100 };
        var priceYRange = calcPriceYRange(klineCtx, initZoom.start, initZoom.end);

        var titleText = data.name + ' - ' + periodName;
        if (data.source) titleText += ' (' + data.source + ')';

        var legendItems = isOamv
            ? [kName, 'CYC5', 'CYC13', 'J']
            : [kName, 'MA60', 'MA8', '知行短期趋势线', '知行多空线', 'J'];

        return {
            title: { text: titleText, left: 'center' },
            animation: false,
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross', link: { xAxisIndex: 'all' } },
                formatter: function (params) {
                    var candle, vol, kdjJ, name;
                    for (var pi = 0; pi < params.length; pi++) {
                        var p = params[pi];
                        if (p.componentSubType === 'candlestick') {
                            candle = p;
                            name = p.name;
                        } else if (p.componentSubType === 'bar' && (p.seriesName === '成交量' || p.seriesName === '成交额')) {
                            vol = p.value != null ? p.value : (p.data && p.data.value);
                        } else if (p.seriesName === 'J') {
                            kdjJ = p.data;
                        }
                    }
                    if (!candle || !candle.data) return '';
                    var d = candle.data;
                    var idx = candle.dataIndex;
                    var pct = idx >= 0 && idx < dailyPctChg.length ? dailyPctChg[idx] : null;
                    var html = (name || '') + '<br>' +
                        '开盘价:' + d[0] + '<br>' +
                        '收盘价:' + d[1] + '<br>' +
                        '最低价:' + d[2] + '<br>' +
                        '最高价:' + d[3] + '<br>' +
                        '涨跌幅:' + formatPctChg(pct);
                    if (vol != null) html += '<br>' + volSeriesName + ':' + vol;
                    if (kdjJ != null && kdjJ !== '-') html += '<br>J:' + kdjJ;
                    return html;
                }
            },
            axisPointer: { link: { xAxisIndex: 'all' } },
            toolbox: { feature: { dataZoom: { yAxisIndex: false } } },
            dataZoom: [
                {
                    type: 'inside',
                    xAxisIndex: [0, 1, 2],
                    start: 10,
                    end: 100,
                    filterMode: 'none',
                    zoomOnMouseWheel: true,
                    moveOnMouseMove: true
                },
                {
                    show: true,
                    xAxisIndex: [0, 1, 2],
                    type: 'slider',
                    bottom: 2,
                    height: 22,
                    start: 10,
                    end: 100,
                    filterMode: 'none'
                }
            ],
            grid: [
                { left: '4%', right: '3%', top: '8%', height: '50%' },
                { left: '4%', right: '3%', top: '60%', height: '14%' },
                { left: '4%', right: '3%', top: '76%', height: '14%' }
            ],
            xAxis: [
                {
                    type: 'category',
                    data: dates,
                    boundaryGap: true,
                    axisLine: { onZero: false },
                    splitLine: { show: false },
                    axisPointer: { z: 100 }
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: dates,
                    boundaryGap: true,
                    axisLine: { onZero: false },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false }
                },
                {
                    type: 'category',
                    gridIndex: 2,
                    data: dates,
                    boundaryGap: true,
                    axisLine: { onZero: false },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: true }
                }
            ],
            yAxis: [
                {
                    name: isOamv ? 'OAMV' : '股价',
                    scale: false,
                    min: priceYRange ? priceYRange.min : null,
                    max: priceYRange ? priceYRange.max : null,
                    splitArea: { show: true }
                },
                {
                    name: volSeriesName,
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLabel: { show: false },
                    axisLine: { show: false },
                    axisTick: { show: false },
                    splitLine: { show: false }
                },
                {
                    name: 'J',
                    scale: true,
                    gridIndex: 2,
                    splitNumber: 4,
                    axisLabel: { show: true },
                    axisLine: { show: true },
                    axisTick: { show: false },
                    splitLine: { show: true }
                }
            ],
            legend: {
                data: legendItems,
                show: true,
                top: '2%',
                type: 'scroll'
            },
            series: [
                {
                    name: kName,
                    type: 'candlestick',
                    data: ohlcList,
                    barWidth: '65%',
                    barMinWidth: 4,
                    barMaxWidth: 48,
                    large: false,
                    itemStyle: {
                        color: 'transparent',
                        color0: downColor,
                        borderColor: upColor,
                        borderColor0: downColor,
                        borderWidth: 1,
                        borderWidth0: 1
                    },
                    emphasis: {
                        itemStyle: {
                            color: 'transparent',
                            borderWidth: 1.5,
                            borderWidth0: 1.5
                        }
                    }
                },
                {
                    name: volSeriesName,
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: volumeBars,
                    barWidth: '65%',
                    barMinWidth: 2,
                    barMaxWidth: 48,
                    large: false
                },
                {
                    name: isOamv ? 'CYC5' : 'MA60',
                    type: 'line',
                    data: isOamv ? cyc5 : ma60,
                    xAxisIndex: 0,
                    yAxisIndex: 0,
                    symbol: 'none',
                    smooth: false,
                    connectNulls: false,
                    lineStyle: { color: '#FFFF00', width: 1.2, opacity: 1 },
                    itemStyle: { color: '#FFFF00' }
                },
                {
                    name: isOamv ? 'CYC13' : 'MA8',
                    type: 'line',
                    data: isOamv ? cyc13 : ma8,
                    xAxisIndex: 0,
                    yAxisIndex: 0,
                    symbol: 'none',
                    smooth: false,
                    connectNulls: false,
                    lineStyle: {
                        color: isOamv ? '#FFFFFF' : '#EF232A',
                        width: 1.2,
                        opacity: 1
                    },
                    itemStyle: { color: isOamv ? '#FFFFFF' : '#EF232A' }
                }
            ].concat(isOamv ? [] : [
                {
                    name: '知行短期趋势线',
                    type: 'line',
                    data: zxShort,
                    xAxisIndex: 0,
                    yAxisIndex: 0,
                    symbol: 'none',
                    smooth: false,
                    connectNulls: false,
                    lineStyle: { color: '#FFFFFF', width: 1, opacity: 1 },
                    itemStyle: { color: '#FFFFFF' }
                },
                {
                    name: '知行多空线',
                    type: 'line',
                    data: zxDuokong,
                    xAxisIndex: 0,
                    yAxisIndex: 0,
                    symbol: 'none',
                    smooth: false,
                    connectNulls: false,
                    lineStyle: { color: '#FFFF00', width: 1.2, opacity: 1 },
                    itemStyle: { color: '#FFFF00' }
                }
            ]).concat([
                {
                    name: 'J',
                    type: 'line',
                    data: jLine,
                    xAxisIndex: 2,
                    yAxisIndex: 2,
                    symbol: 'none',
                    connectNulls: false,
                    lineStyle: { color: '#ff00ff', width: 1.2 },
                    z: 3,
                    markPoint: {
                        silent: true,
                        symbol: 'arrow',
                        symbolRotate: 180,
                        symbolSize: 9,
                        symbolOffset: [0, 4],
                        z: 1,
                        itemStyle: { color: '#EF232A', borderColor: '#EF232A' },
                        label: { show: false },
                        data: jBelowZeroArrows
                    },
                    markLine: {
                        silent: true,
                        symbol: 'none',
                        lineStyle: { type: 'solid', width: 1 },
                        label: { show: false },
                        data: [
                            { yAxis: 100, lineStyle: { color: '#ffffff' } },
                            { yAxis: 13, lineStyle: { color: '#ffffff' } },
                            { yAxis: 0, lineStyle: { color: '#ffff00' } }
                        ]
                    }
                }
            ]),
            _saKlineCtx: klineCtx
        };
    }

    function renderKlineChart(domId, data, chartHolder) {
        var chartDom = document.getElementById(domId);
        if (!chartDom) return null;
        if (chartHolder.instance) {
            chartHolder.instance.dispose();
        }
        chartHolder.instance = echarts.init(chartDom, null, { renderer: 'canvas' });
        var option = buildKlineChartOption(data);
        var klineCtx = option._saKlineCtx;
        delete option._saKlineCtx;
        if (typeof applySaChartDark === 'function') {
            applySaChartDark(option);
        }
        chartHolder.instance.setOption(option, true);
        chartHolder.instance.resize();
        if (klineCtx) {
            bindPriceAxisAutoFit(chartHolder.instance, chartHolder, klineCtx);
        }
        return chartHolder.instance;
    }

    function renderDailyPctTable(containerId, data) {
        var el = document.getElementById(containerId);
        if (!el || !data || !data.klines || !data.dates) return;

        var rows = [];
        for (var i = 0; i < data.klines.length; i++) {
            var row = data.klines[i];
            if (!row || row.length < 2) continue;
            var close = parseFloat(row[1]);
            var pct = null;
            if (i > 0) {
                var prev = parseFloat(data.klines[i - 1][1]);
                if (prev > 0) pct = ((close - prev) / prev) * 100;
            }
            rows.push({
                date: data.dates[i],
                close: close,
                pct: pct
            });
        }
        rows.reverse();
        var limit = Math.min(rows.length, 60);
        var html = '<div class="table-responsive sa-pct-table-wrap"><table class="table table-sm table-hover mb-0">' +
            '<thead><tr><th>日期</th><th class="text-end">收盘</th><th class="text-end">涨跌幅</th></tr></thead><tbody>';
        for (var ri = 0; ri < limit; ri++) {
            var r = rows[ri];
            var cls = 'text-secondary';
            if (r.pct != null && !isNaN(r.pct)) {
                cls = r.pct > 0 ? 'sa-chg-up' : (r.pct < 0 ? 'sa-chg-down' : 'sa-chg-flat');
            }
            html += '<tr><td>' + r.date + '</td><td class="text-end">' +
                (isNaN(r.close) ? '—' : r.close.toFixed(2)) + '</td><td class="text-end ' + cls + '">' +
                formatPctChg(r.pct) + '</td></tr>';
        }
        html += '</tbody></table></div>';
        if (rows.length > limit) {
            html += '<p class="text-muted small mb-0 mt-2">仅展示最近 ' + limit + ' 个交易日</p>';
        }
        el.innerHTML = html;
    }

    global.buildKlineChartOption = buildKlineChartOption;
    global.renderKlineChart = renderKlineChart;
    global.renderDailyPctTable = renderDailyPctTable;
})(typeof window !== 'undefined' ? window : this);
