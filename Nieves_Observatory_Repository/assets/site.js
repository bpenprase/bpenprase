(function () {
  var githubConfig = {
    owner: 'bpenprase',
    repo: 'bpenprase',
    branch: 'main',
    contentRoot: 'Nieves_Observatory_Repository/content',
    sectionRoots: {
      publications: [
        'Nieves_Observatory_Repository/publications',
        'Nieves_Observatory_Repository/content/publications'
      ],
      datasets: [
        'Nieves_Observatory_Repository/datasets',
        'Nieves_Observatory_Repository/content/datasets'
      ],
      software: [
        'Nieves_Observatory_Repository/software',
        'Nieves_Observatory_Repository/content/software'
      ],
      gallery: [
        'Nieves_Observatory_Repository/gallery',
        'Nieves_Observatory_Repository/content/gallery'
      ]
    }
  };

  function initMenuToggle() {
    var toggle = document.querySelector('.menu-toggle');
    var nav = document.querySelector('.main-nav');
    if (!toggle || !nav) {
      return;
    }

    toggle.addEventListener('click', function () {
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      nav.classList.toggle('open');
    });
  }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) {
      return 'Unknown size';
    }
    var units = ['B', 'KB', 'MB', 'GB'];
    var value = bytes;
    var index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return value.toFixed(index === 0 ? 0 : 1) + ' ' + units[index];
  }

  function formatDate(isoDate) {
    if (!isoDate) {
      return 'Unknown date';
    }
    var dt = new Date(isoDate);
    if (Number.isNaN(dt.getTime())) {
      return 'Unknown date';
    }
    return dt.toLocaleString();
  }

  function renderEmptyState(container, message) {
    container.innerHTML = '';
    var node = document.createElement('div');
    node.className = 'empty-state';
    node.textContent = message;
    container.appendChild(node);
  }

  function normalizeGitHubFiles(items) {
    return items
      .filter(function (item) {
        return item.type === 'file' && item.name !== 'index.html' && item.name !== 'external-files.json';
      })
      .sort(function (a, b) {
        return a.name.localeCompare(b.name);
      })
      .map(function (item) {
        return {
          name: item.name,
          size: item.size,
          modified: null,
          url: item.download_url || item.html_url
        };
      });
  }

  function isWebImage(fileName) {
    var lower = String(fileName || '').toLowerCase();
    return lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.png') || lower.endsWith('.webp') || lower.endsWith('.gif');
  }

  async function fetchExternalManifest(root) {
    var endpoint =
      'https://raw.githubusercontent.com/' + githubConfig.owner + '/' + githubConfig.repo + '/' + githubConfig.branch +
      '/' + root + '/external-files.json';

    var response = await fetch(endpoint, {
      headers: {
        Accept: 'application/json'
      }
    });

    if (!response.ok) {
      return [];
    }

    var payload = await response.json();
    if (!Array.isArray(payload)) {
      return [];
    }

    return payload
      .filter(function (item) {
        return item && item.name && item.url;
      })
      .map(function (item) {
        return {
          name: item.name,
          size: item.size,
          modified: item.modified || null,
          url: item.url
        };
      });
  }

  async function fetchFromGitHub(section) {
    var roots = githubConfig.sectionRoots[section] || [githubConfig.contentRoot + '/' + section];
    var results = await Promise.all(
      roots.map(async function (root) {
        var endpoint =
          'https://api.github.com/repos/' + githubConfig.owner + '/' + githubConfig.repo +
          '/contents/' + root + '?ref=' + githubConfig.branch;

        var response = await fetch(endpoint, {
          headers: {
            Accept: 'application/vnd.github+json'
          }
        });

        if (!response.ok) {
          throw new Error('GitHub content request failed with status ' + response.status);
        }

        var payload = await response.json();
        if (!Array.isArray(payload)) {
          return [];
        }

        return normalizeGitHubFiles(payload);
      })
    );

    var externalResults = await Promise.all(
      roots.map(function (root) {
        return fetchExternalManifest(root);
      })
    );

    return results.flat().concat(externalResults.flat()).sort(function (a, b) {
      return a.name.localeCompare(b.name);
    });
  }

  function createFileCard(file) {
    var article = document.createElement('article');
    article.className = 'file-card';

    var title = document.createElement('h3');
    title.textContent = file.name;
    article.appendChild(title);

    var size = document.createElement('p');
    size.className = 'file-meta';
    size.textContent = 'Size: ' + formatSize(file.size);
    article.appendChild(size);

    var updated = document.createElement('p');
    updated.className = 'file-meta';
    updated.textContent = 'Updated: ' + formatDate(file.modified);
    article.appendChild(updated);

    var link = document.createElement('a');
    link.className = 'file-link';
    link.href = file.url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Open file';
    article.appendChild(link);

    return article;
  }

  function createGalleryItem(file) {
    var article = document.createElement('article');
    article.className = 'gallery-item';

    var image = document.createElement('img');
    image.src = file.url;
    image.alt = file.name;
    image.loading = 'lazy';
    article.appendChild(image);

    var caption = document.createElement('div');
    caption.className = 'gallery-caption';
    caption.innerHTML = '<strong>' + file.name + '</strong><br><span class="file-meta">' + formatDate(file.modified) + '</span>';
    article.appendChild(caption);

    return article;
  }

  async function loadRepositorySection() {
    var section = document.body.getAttribute('data-section');
    var viewType = document.body.getAttribute('data-view');
    if (!section || !viewType) {
      return;
    }

    var container = document.getElementById(viewType === 'gallery' ? 'gallery-grid' : 'file-grid');
    if (!container) {
      return;
    }

    try {
      var response = await fetch('/api/repository/list/' + section);
      if (!response.ok) {
        throw new Error('Request failed with status ' + response.status);
      }

      var payload = await response.json();
      var files = payload.files || [];
      if (files.length === 0) {
        renderEmptyState(container, 'No files found yet. Add files to content/' + section + ' and refresh this page.');
        return;
      }

      container.innerHTML = '';
      files.forEach(function (file) {
        if (viewType === 'gallery' && !isWebImage(file.name)) {
          container.appendChild(createFileCard(file));
          return;
        }

        container.appendChild(viewType === 'gallery' ? createGalleryItem(file) : createFileCard(file));
      });
    } catch (error) {
      try {
        var githubFiles = await fetchFromGitHub(section);
        if (githubFiles.length === 0) {
          renderEmptyState(container, 'No files found yet. Add files to content/' + section + ' and push your changes.');
          return;
        }

        container.innerHTML = '';
        githubFiles.forEach(function (file) {
          if (viewType === 'gallery' && !isWebImage(file.name)) {
            container.appendChild(createFileCard(file));
            return;
          }

          container.appendChild(viewType === 'gallery' ? createGalleryItem(file) : createFileCard(file));
        });
      } catch (githubError) {
        renderEmptyState(container, 'Could not load files from local API or GitHub Pages.');
      }
    }
  }

  initMenuToggle();
  loadRepositorySection();
})();
