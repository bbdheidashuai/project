/**
 * ECharts 深色主题：与全站 sa-dark-theme 一致
 */
(function (global) {
  var axisBase = {
    axisLine: { lineStyle: { color: '#475569' } },
    axisLabel: { color: '#94a3b8' },
    splitLine: { lineStyle: { color: 'rgba(51, 65, 85, 0.65)' } },
    nameTextStyle: { color: '#94a3b8' },
  };

  function mergeAxis(ax) {
    if (!ax) {
      return ax;
    }
    if (Array.isArray(ax)) {
      return ax.map(mergeAxis);
    }
    return Object.assign({}, axisBase, ax, {
      axisLine: Object.assign({}, axisBase.axisLine, ax.axisLine),
      axisLabel: Object.assign({}, axisBase.axisLabel, ax.axisLabel),
      splitLine: Object.assign({}, axisBase.splitLine, ax.splitLine),
      nameTextStyle: Object.assign({}, axisBase.nameTextStyle, ax.nameTextStyle),
    });
  }

  function applySaChartDark(option) {
    if (!option) {
      return option;
    }
    option.backgroundColor = option.backgroundColor || 'transparent';
    option.textStyle = Object.assign({ color: '#94a3b8' }, option.textStyle || {});

    if (option.title) {
      var patchTitle = function (t) {
        return Object.assign({}, t, {
          textStyle: Object.assign({ color: '#f1f5f9' }, t.textStyle || {}),
        });
      };
      option.title = Array.isArray(option.title)
        ? option.title.map(patchTitle)
        : patchTitle(option.title);
    }

    if (option.legend) {
      option.legend = Object.assign({}, option.legend, {
        textStyle: Object.assign({ color: '#94a3b8' }, option.legend.textStyle || {}),
      });
    }

    option.tooltip = Object.assign(
      {
        backgroundColor: 'rgba(15, 23, 42, 0.96)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0' },
      },
      option.tooltip || {}
    );

    option.xAxis = mergeAxis(option.xAxis);
    option.yAxis = mergeAxis(option.yAxis);

    if (option.yAxis) {
      var yAxes = Array.isArray(option.yAxis) ? option.yAxis : [option.yAxis];
      yAxes.forEach(function (y) {
        if (y && y.splitArea && y.splitArea.show) {
          y.splitArea = Object.assign({}, y.splitArea, {
            areaStyle: {
              color: ['rgba(30, 41, 59, 0.35)', 'rgba(15, 23, 42, 0.2)'],
            },
          });
        }
      });
    }

    if (option.dataZoom) {
      var dzList = Array.isArray(option.dataZoom) ? option.dataZoom : [option.dataZoom];
      option.dataZoom = dzList.map(function (z) {
        return Object.assign({}, z, {
          textStyle: { color: '#94a3b8' },
          borderColor: '#334155',
          backgroundColor: 'rgba(17, 24, 39, 0.85)',
          fillerColor: 'rgba(34, 211, 238, 0.18)',
          handleStyle: { color: '#22d3ee', borderColor: '#22d3ee' },
          dataBackground: {
            lineStyle: { color: '#64748b' },
            areaStyle: { color: 'rgba(30, 41, 59, 0.6)' },
          },
        });
      });
    }

    return option;
  }

  global.applySaChartDark = applySaChartDark;
})(typeof window !== 'undefined' ? window : this);
